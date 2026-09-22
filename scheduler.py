"""
Fraud Detection Pipeline Scheduler
===================================
Automated fetch → preprocess → analyze pipeline using APScheduler.

Designed as the automation foundation for eventual ML pipeline migration:
  - Every run records a config snapshot (feature schema version, thresholds used)
    so future ML training datasets can be reconstructed with exact parameters.
  - Pipeline run lineage is stored in pipeline_runs table.
  - Analysis aligns with the dashboard run_analysis() path (preprocess, detector,
    affiliate/campaign fallbacks, DUID handling). Rows are filtered by calendar
    transaction date via DATE(trans_datetime) (same semantics as API trans_date).
  - After each pipeline: small admin API "fresh" enrichment batch for that run;
    a separate interval job (enrich_backlog) drains the global unenriched backlog.

Cron times use the scheduler timezone (UTC). Example: hour=14 = 14:00 UTC
    (10:00 Eastern during EDT). Use hour=15 for ~11:00 Eastern if you need a buffer
    after connecting VPN.

Optional ``scheduler.vpn_probe_url``: if set, scheduled and catchup runs wait until the
    HTTP probe succeeds. When empty, ``vpn_use_api_probe`` (default true) uses affiliate
    API ``a=me`` as probe — retries for ``vpn_probe_retry_max_minutes`` after boot/VPN delay.

Jobs are persisted in ``apscheduler_jobs.sqlite`` next to the affiliate DB so
fire times survive Flask restarts. Run only one scheduler process: either
embedded in ``python run.py`` or standalone ``python scheduler.py`` — if using
standalone, set env ``SKIP_EMBEDDED_SCHEDULER=1`` when starting the web app.

Usage:
    scheduler = FraudPipelineScheduler(db, config, api_client)
    scheduler.start()           # boots background scheduler
    scheduler.trigger_now()     # immediate manual run
    scheduler.update_schedule(enabled=True, hour=14, minute=0, days_back=1)
    scheduler.stop()
"""

import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from database import Database

logger = logging.getLogger(__name__)

# ── State shared with dashboard API endpoints ─────────────────────────────────
_current_run: dict = {}   # {run_id, status, progress, started, ...}
_run_lock = threading.Lock()
_pipeline_busy = threading.Lock()  # prevents overlapping manual + scheduled runs
_enrich_backlog_busy = threading.Lock()  # at most one backlog enrichment at a time
_startup_catchup_armed = True       # one automatic catch-up per process (after Timer fires)
_vpn_wait_status: dict = {}         # last VPN wait outcome for /api/scheduler/status
_current_coverage_audit: dict = {}    # last coverage audit summary
_current_analysis_backlog: dict = {}  # last analysis backlog drain summary
_coverage_fetch_busy = threading.Lock()


def iter_catchup_day_range(total_days_back: int, end_date=None):
    """
    Yield YYYY-MM-DD for each calendar day in the catch-up window.

    Matches _run_pipeline days_back semantics: [end - total_days_back, end] inclusive.
    """
    if total_days_back < 1:
        return
    if end_date is None:
        end = datetime.now().date()
    elif isinstance(end_date, datetime):
        end = end_date.date()
    else:
        end = end_date
    start = end - timedelta(days=int(total_days_back))
    current = start
    while current <= end:
        yield current.strftime('%Y-%m-%d')
        current += timedelta(days=1)
_stale_notify_sent = False          # one stale warning per process
_current_enrich_backlog: dict = {}  # last backlog job summary for /api/scheduler/status


class FraudPipelineScheduler:
    """
    Wraps APScheduler to run the fraud detection pipeline on a configurable
    cron schedule.  Falls back gracefully if APScheduler is not installed.
    """

    def __init__(self, db, config, api_client=None):
        self.db         = db
        self.config     = config
        self.api_client = api_client
        self._scheduler = None
        self._available = self._check_apscheduler()

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_api_client(self, api_client):
        self.api_client = api_client

    @staticmethod
    def _jobstore_url_for_db(db_path: str) -> str:
        """SQLite URL for APScheduler job persistence (alongside affiliate DB)."""
        parent = Path(db_path).expanduser().resolve().parent
        job_file = parent / 'apscheduler_jobs.sqlite'
        # SQLAlchemy sqlite URL: absolute path with three slashes after sqlite:
        return 'sqlite:///' + str(job_file).replace('\\', '/')

    def start(self):
        """Boot the background scheduler using current config."""
        if not self._available:
            logger.warning("APScheduler not installed — scheduled jobs disabled. "
                           "Run: pip install apscheduler")
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            db_path = getattr(self.db, 'db_path', None) or 'affiliate_data.db'
            job_defaults = {
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 7200,  # 2h late window (laptop sleep / brief downtime)
            }
            jobstores = None
            jobstore_note = 'memory (install sqlalchemy for persistent job store)'

            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

                jobstore_url = self._jobstore_url_for_db(db_path)
                jobstores = {
                    'default': SQLAlchemyJobStore(
                        url=jobstore_url,
                        engine_options={'connect_args': {'check_same_thread': False}},
                    ),
                }
                jobstore_note = jobstore_url
            except ImportError:
                logger.warning(
                    'SQLAlchemy not installed — scheduler jobs are in-memory only '
                    '(survive restarts after: pip install sqlalchemy).'
                )

            kw = {'job_defaults': job_defaults, 'timezone': 'UTC'}
            if jobstores:
                kw['jobstores'] = jobstores
            self._scheduler = BackgroundScheduler(**kw)

            sched_cfg = self.config.get('scheduler', {})
            self._scheduler.start()

            if sched_cfg.get('enabled', False):
                self._register_job(sched_cfg)
            else:
                try:
                    self._scheduler.remove_job('fetch_and_analyze')
                except Exception:
                    pass

            self._register_enrich_backlog_job()
            self._register_coverage_audit_job()
            self._register_analysis_backlog_job()

            logger.info('Pipeline scheduler started (job store: %s)', jobstore_note)
            self._schedule_post_start_hooks()
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}", exc_info=True)

    def _schedule_post_start_hooks(self):
        """Deferred startup catch-up + stale notification (non-blocking)."""
        if os.environ.get('SKIP_EMBEDDED_SCHEDULER', '').lower() in ('1', 'true', 'yes'):
            return

        def _catchup():
            try:
                self.maybe_startup_catchup()
            except Exception as e:
                logger.error('Startup catch-up error: %s', e, exc_info=True)

        def _stale():
            try:
                self.maybe_notify_embedded_stale_once()
            except Exception as e:
                logger.error('Stale-schedule notify error: %s', e, exc_info=True)

        sched_cfg = self.config.get('scheduler', {}) or {}
        delay = float(sched_cfg.get('startup_catchup_delay_seconds', 120) or 120)
        delay = max(0.0, min(delay, 3600.0))
        threading.Timer(delay, _catchup).start()
        threading.Timer(delay + 8.0, _stale).start()

    def stop(self):
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Pipeline scheduler stopped")

    def trigger_now(self, days_back: int = 1):
        """Kick off an immediate pipeline run in a background thread."""
        t = threading.Thread(
            target=self._run_pipeline,
            kwargs={'days_back': days_back, 'trigger': 'manual'},
            daemon=True,
            name='pipeline-manual',
        )
        t.start()
        return True

    def trigger_day(self, day: str, trigger: str = 'manual'):
        """Fetch + analyze a single calendar day immediately."""
        day = str(day or '').strip()[:10]
        if len(day) != 10:
            return False
        t = threading.Thread(
            target=self._run_pipeline,
            kwargs={
                'days_back': 1,
                'trigger': trigger,
                'start_date': day,
                'end_date': day,
            },
            daemon=True,
            name=f'pipeline-day-{day}',
        )
        t.start()
        return True

    def update_schedule(self, enabled: bool, hour: int = 2, minute: int = 0,
                        days_back: int = 1):
        """Persist schedule config and reconfigure the live scheduler."""
        merged = dict(self.config.get('scheduler', {}))
        merged.update({
            'enabled':   enabled,
            'hour':      hour,
            'minute':    minute,
            'days_back': days_back,
        })
        self.config.set('scheduler', merged)

        if not self._scheduler:
            return

        if enabled:
            self._register_job({'enabled': True, 'hour': hour,
                                 'minute': minute, 'days_back': days_back})
            logger.info(f"Schedule updated: daily at {hour:02d}:{minute:02d}, "
                        f"fetching last {days_back} day(s)")
        else:
            try:
                self._scheduler.remove_job('fetch_and_analyze')
            except Exception:
                pass
            logger.info("Scheduled job disabled")

        self._register_enrich_backlog_job()
        self._register_coverage_audit_job()
        self._register_analysis_backlog_job()

    def get_status(self) -> dict:
        """Return scheduler status for the dashboard API."""
        sched_cfg = self.config.get('scheduler', {})
        eb_cfg = sched_cfg.get('enrich_backlog')
        if not isinstance(eb_cfg, dict):
            eb_cfg = {}
        status = {
            'scheduler_available': self._available,
            'scheduler_running':   bool(self._scheduler and self._scheduler.running),
            'enabled':             sched_cfg.get('enabled', False),
            'hour':                sched_cfg.get('hour', 14),
            'minute':              sched_cfg.get('minute', 0),
            'days_back':           sched_cfg.get('days_back', 1),
            'startup_catchup':     sched_cfg.get('startup_catchup', True),
            'notify_macos':        sched_cfg.get('notify_macos', True),
            'startup_catchup_max_days': int(sched_cfg.get('startup_catchup_max_days', 31)),
            'startup_catchup_after_hours': float(sched_cfg.get('startup_catchup_after_hours', 26)),
            'catchup_skip_enrichment': sched_cfg.get('catchup_skip_enrichment', True),
            'catchup_chunk_days': sched_cfg.get('catchup_chunk_days', True),
            'stale_after_hours': float(sched_cfg.get('stale_after_hours', 80)),
            'next_run':            None,
            'current_run':         dict(_current_run),
            'enrich_after_pipeline': sched_cfg.get('enrich_after_pipeline', True),
            'enrich_fresh_limit': int(sched_cfg.get('enrich_fresh_limit', 500) or 500),
            'enrich_lookback_days': int(sched_cfg.get('enrich_lookback_days', 90) or 90),
            'enrich_max_transient_attempts': int(sched_cfg.get('enrich_max_transient_attempts', 5) or 5),
            'enrich_health_check': bool(sched_cfg.get('enrich_health_check', True)),
            'enrich_backlog': {
                'enabled': bool(eb_cfg.get('enabled', True)),
                'interval_minutes': int(eb_cfg.get('interval_minutes', 15) or 15),
                'batch_limit': int(eb_cfg.get('batch_limit', 2000) or 2000),
                'throttle_seconds': float(eb_cfg.get('throttle_seconds', 0.25) or 0),
            },
            'enrich_backlog_next': None,
            'enrichment_backlog_count': 0,
            'enrich_backlog_last': dict(_current_enrich_backlog),
            'vpn_probe_enabled': self._vpn_probe_configured(),
            'vpn_wait': dict(_vpn_wait_status),
            'coverage_audit_last': dict(_current_coverage_audit),
            'analysis_backlog_last': dict(_current_analysis_backlog),
        }

        try:
            lb = int(sched_cfg.get('enrich_lookback_days', 90) or 90)
            status['enrich_lookback_days'] = lb
            status['enrich_max_transient_attempts'] = int(
                sched_cfg.get('enrich_max_transient_attempts', 5) or 5
            )
            status['enrich_health_check'] = bool(sched_cfg.get('enrich_health_check', True))
            status['enrichment_backlog_count'] = int(
                self.db.get_enrichment_backlog_count(lookback_days=lb)
            )
        except Exception as e:
            logger.debug('enrichment_backlog_count: %s', e)

        if self._scheduler:
            job = self._scheduler.get_job('fetch_and_analyze')
            if job and job.next_run_time:
                status['next_run'] = job.next_run_time.isoformat()
            eb_job = self._scheduler.get_job('enrich_backlog')
            if eb_job and eb_job.next_run_time:
                status['enrich_backlog_next'] = eb_job.next_run_time.isoformat()
            ca_job = self._scheduler.get_job('coverage_audit')
            if ca_job and ca_job.next_run_time:
                status['coverage_audit_next'] = ca_job.next_run_time.isoformat()
            ab_job = self._scheduler.get_job('analysis_backlog')
            if ab_job and ab_job.next_run_time:
                status['analysis_backlog_next'] = ab_job.next_run_time.isoformat()

        # Attach last completed run
        history = self.db.get_pipeline_history(limit=1)
        status['last_run'] = history[0] if history else None
        status['scheduled_health'] = self._scheduled_health(
            sched_cfg, status['next_run'],
            embedded_skipped=os.environ.get('SKIP_EMBEDDED_SCHEDULER', '').lower()
            in ('1', 'true', 'yes'),
        )
        try:
            status['catchup_suggestion'] = self.compute_catchup_suggestion()
        except Exception as e:
            logger.debug('catchup_suggestion: %s', e)
            status['catchup_suggestion'] = {'ok': False, 'error': str(e)}
        try:
            status['coverage_health'] = self.compute_coverage_health()
        except Exception as e:
            logger.debug('coverage_health: %s', e)
            status['coverage_health'] = {'ok': False, 'error': str(e)}
        try:
            ab_cfg = sched_cfg.get('analysis_backlog') or {}
            lb = int(ab_cfg.get('lookback_days', 14) or 14)
            status['analysis_backlog_count'] = int(
                self.db.get_analysis_backlog_count(lookback_days=lb)
            )
        except Exception as e:
            logger.debug('analysis_backlog_count: %s', e)
            status['analysis_backlog_count'] = None
        return status

    def get_history(self, limit: int = 20) -> list:
        return self.db.get_pipeline_history(limit=limit)

    def compute_catchup_suggestion(self) -> dict:
        """Suggest days_back from time since last completed pipeline (any run_type)."""
        import math

        sched = self.config.get('scheduler', {})
        max_days = int(sched.get('startup_catchup_max_days', 14))
        after_h = float(sched.get('startup_catchup_after_hours', 26))

        row = self.db.get_last_pipeline_run(status='completed')
        if not row or not row.get('completed_at'):
            return {
                'ok': True,
                'days_back': 0,
                'hours_since_last': None,
                'last_completed_at': None,
                'last_run_type': None,
                'reason': 'no_completed_runs',
                'message': 'No completed pipeline runs yet.',
            }

        last_dt = self._parse_ts_loose(row['completed_at'])
        if not last_dt:
            return {'ok': False, 'days_back': 0, 'reason': 'parse_error', 'message': 'Could not parse last completed_at.'}

        hours = (datetime.now() - last_dt).total_seconds() / 3600
        if hours < after_h:
            return {
                'ok': True,
                'days_back': 0,
                'hours_since_last': round(hours, 2),
                'last_completed_at': row['completed_at'],
                'last_run_type': row.get('run_type'),
                'reason': 'recent',
                'message': f'Last completion {hours:.1f}h ago — within normal window.',
            }

        days_back = min(max_days, max(1, int(math.ceil(hours / 24.0))))
        capped = days_back >= max_days
        return {
            'ok': True,
            'days_back': days_back,
            'hours_since_last': round(hours, 2),
            'last_completed_at': row['completed_at'],
            'last_run_type': row.get('run_type'),
            'capped_at_max': capped,
            'reason': 'gap',
            'message': (
                f'~{hours:.0f}h since last completion — suggested lookback {days_back} day(s)'
                + (f' (capped at {max_days})' if capped else '')
            ),
        }

    def maybe_startup_catchup(self):
        global _startup_catchup_armed
        if not _startup_catchup_armed:
            return
        if os.environ.get('SKIP_EMBEDDED_SCHEDULER', '').lower() in ('1', 'true', 'yes'):
            return
        if not self._available:
            return
        sched = self.config.get('scheduler', {})
        if not sched.get('enabled', False):
            return
        if not sched.get('startup_catchup', True):
            return
        if not self.api_client:
            logger.warning('Startup catch-up skipped: API client not configured')
            _startup_catchup_armed = False
            return
        try:
            stale_hours = float((self.config.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
            n = self.db.fail_stale_pipeline_runs(stale_hours=stale_hours)
            if n:
                logger.info('Startup catch-up: cleared %s stale pipeline_runs', n)
        except Exception as e:
            logger.warning('fail_stale_pipeline_runs before catch-up: %s', e)
        if self._pipeline_running_in_db():
            logger.info('Startup catch-up skipped: pipeline_runs has status=running')
            return
        with _run_lock:
            if _current_run.get('status') == 'running':
                return

        sug = self.compute_catchup_suggestion()
        days = int(sug.get('days_back') or 0)
        missing = self._get_refetch_days()
        if days < 1 and not missing:
            _startup_catchup_armed = False
            return

        sched = self.config.get('scheduler', {}) or {}
        if sched.get('startup_catchup_wait_for_vpn', True):
            if not self._wait_for_vpn('catchup'):
                logger.warning('Startup catch-up deferred: VPN/API not ready after retries')
                if self._should_notify_macos():
                    self._notify_macos(
                        'Fraud pipeline — waiting for VPN',
                        'Startup catch-up paused until affiliate API is reachable.',
                    )
                return

        _startup_catchup_armed = False

        if missing and sched.get('coverage_audit', {}).get('auto_fetch_missing', True):
            logger.info(
                'Startup catch-up: fetching %s missing day(s): %s',
                len(missing),
                ', '.join(missing),
            )
            if self._should_notify_macos():
                self._notify_macos(
                    'Fraud pipeline — missing dates',
                    f'Auto-fetching {len(missing)} missing day(s).',
                )
            self._fetch_missing_days(missing)
            return

        if days < 1:
            return

        logger.info(
            'Startup catch-up: %.1fh since last completion — %s day(s) lookback',
            float(sug.get('hours_since_last') or 0),
            days,
        )
        if self._should_notify_macos():
            self._notify_macos(
                'Fraud pipeline — catch-up',
                f'Starting automatic backfill ({days} day lookback).',
            )
        self.trigger_catchup(days_back=days)

    def trigger_catchup(self, days_back: int = 1):
        """Background catch-up run (recorded as run_type=catchup)."""
        days_back = max(1, min(int(days_back), 90))
        sched = self.config.get('scheduler', {}) or {}
        chunk = bool(sched.get('catchup_chunk_days', True)) and days_back > 1
        if chunk:
            t = threading.Thread(
                target=self._run_catchup_chunked,
                kwargs={'total_days_back': days_back},
                daemon=True,
                name='pipeline-catchup-chunked',
            )
        else:
            t = threading.Thread(
                target=self._run_pipeline,
                kwargs={'days_back': days_back, 'trigger': 'catchup'},
                daemon=True,
                name='pipeline-catchup',
            )
        t.start()
        return True

    def _run_catchup_chunked(self, total_days_back: int):
        """Run catch-up one calendar day at a time (oldest first)."""
        day_list = list(iter_catchup_day_range(total_days_back))
        total = len(day_list)
        logger.info(
            'Catch-up chunking: %s day(s) — %s',
            total,
            ', '.join(day_list),
        )
        for idx, day_str in enumerate(day_list, start=1):
            logger.info('Catch-up chunk %s/%s: %s', idx, total, day_str)
            self._run_pipeline(
                days_back=1,
                trigger='catchup',
                start_date=day_str,
                end_date=day_str,
                catchup_chunk={'index': idx, 'total': total, 'day': day_str},
            )

    def maybe_notify_embedded_stale_once(self):
        global _stale_notify_sent
        if _stale_notify_sent:
            return
        if not self._should_notify_macos():
            return
        if os.environ.get('SKIP_EMBEDDED_SCHEDULER', '').lower() in ('1', 'true', 'yes'):
            return
        sched_cfg = self.config.get('scheduler', {})
        if not sched_cfg.get('enabled', False):
            return
        next_run = None
        if self._scheduler:
            job = self._scheduler.get_job('fetch_and_analyze')
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()
        health = self._scheduled_health(sched_cfg, next_run, embedded_skipped=False)
        if not health.get('stale') or not health.get('message'):
            return
        _stale_notify_sent = True
        self._notify_macos('Fraud pipeline — schedule', health['message'][:500])

    def _pipeline_running_in_db(self) -> bool:
        try:
            with self.db.get_connection() as conn:
                r = conn.execute(
                    "SELECT 1 FROM pipeline_runs WHERE status = 'running' LIMIT 1"
                ).fetchone()
                return r is not None
        except Exception:
            return False

    def _should_notify_macos(self) -> bool:
        if sys.platform != 'darwin':
            return False
        if os.environ.get('FRAUD_NOTIFY_MACOS', '').lower() in ('0', 'false', 'no'):
            return False
        return bool(self.config.get('scheduler', {}).get('notify_macos', True))

    def _notify_macos(self, title: str, subtitle: str):
        if sys.platform != 'darwin':
            return
        if os.environ.get('FRAUD_NOTIFY_MACOS', '').lower() in ('0', 'false', 'no'):
            return
        try:
            import subprocess

            safe_t = (title or '').replace('\\', '\\\\').replace('"', '\\"')[:120]
            safe_s = (subtitle or '').replace('\\', '\\\\').replace('"', '\\"')[:500]
            subprocess.run(
                [
                    '/usr/bin/osascript', '-e',
                    f'display notification "{safe_s}" with title "{safe_t}"',
                ],
                timeout=5,
                capture_output=True,
                check=False,
            )
        except Exception as e:
            logger.debug('macOS notification failed: %s', e)

    def compute_coverage_health(self) -> dict:
        """Daily fetch/analysis coverage for dashboard health."""
        sched = self.config.get('scheduler', {}) or {}
        ca = sched.get('coverage_audit') or {}
        lookback = int(ca.get('lookback_days', 14) or 14)
        end = datetime.now().date()
        start = end - timedelta(days=max(1, lookback) - 1)
        start_s = start.strftime('%Y-%m-%d')
        end_s = end.strftime('%Y-%m-%d')

        scripts_path = str(Path(__file__).parent / 'scripts')
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from coverage_audit import detect_coverage_gaps

        exclude_today = None
        if ca.get('exclude_today_from_refetch', True):
            exclude_today = [end.strftime('%Y-%m-%d')]

        report = detect_coverage_gaps(
            self.db,
            start_s,
            end_s,
            min_neighbor_rows=int(ca.get('min_neighbor_rows', 1000) or 1000),
            detect_partial=bool(ca.get('detect_partial_days', True)),
            partial_min_rows=int(ca.get('partial_fetch_min_rows', 5000) or 5000),
            partial_ratio=float(ca.get('partial_fetch_ratio', 0.55) or 0.55),
            exclude_days=exclude_today,
        )

        # Merge stored MCP/PS7 reconciliation into coverage report
        mrc = sched.get('mcp_reconciliation') or {}
        if isinstance(mrc, dict) and mrc.get('enabled', True):
            scripts_path = str(Path(__file__).parent / 'scripts')
            if scripts_path not in sys.path:
                sys.path.insert(0, scripts_path)
            from source_reconciliation import (
                build_source_client,
                merge_reconciliation_into_coverage,
                reconcile_day_range,
                reconciliation_source_configured,
            )

            source = str(mrc.get('source') or 'mcp_ps7_ht_signups')
            recon_by_day = self.db.get_reconciliation_results(start_s, end_s, source=source)
            refresh_h = float(mrc.get('refresh_interval_hours', 6) or 6)
            stale_days = []
            for day_str in iter_catchup_day_range(
                max(1, lookback), end_date=end,
            ):
                if exclude_today and day_str in (exclude_today or []):
                    continue
                rec = recon_by_day.get(day_str)
                if not rec or not rec.get('reconciliation_checked_at'):
                    stale_days.append(day_str)
                    continue
                try:
                    checked = self._parse_ts_loose(rec['reconciliation_checked_at'])
                    if checked and (
                        datetime.now() - checked
                    ).total_seconds() > refresh_h * 3600:
                        stale_days.append(day_str)
                except Exception:
                    stale_days.append(day_str)

            if stale_days and reconciliation_source_configured(self.config):
                try:
                    client = build_source_client(self.config)
                    reconcile_day_range(
                        self.db,
                        self.config,
                        client,
                        min(stale_days),
                        max(stale_days),
                    )
                    recon_by_day = self.db.get_reconciliation_results(
                        start_s, end_s, source=source,
                    )
                except Exception as exc:
                    logger.debug('MCP reconciliation refresh skipped: %s', exc)

            report = merge_reconciliation_into_coverage(
                report,
                recon_by_day,
                threshold_pct=float(mrc.get('match_threshold_pct', 99.5) or 99.5),
            )

        missing = report.get('missing_days') or []
        partial = report.get('partial_days') or []
        refetch = report.get('refetch_days') or []
        daily = report.get('daily') or []
        pending = int(report.get('pending_analysis_total') or 0)
        ab_cfg = sched.get('analysis_backlog') or {}
        backlog = int(self.db.get_analysis_backlog_count(
            lookback_days=int(ab_cfg.get('lookback_days', lookback) or lookback),
        ))

        msg_parts = []
        if missing:
            msg_parts.append(
                f'{len(missing)} missing fetch day(s): '
                + ', '.join(m['day'] for m in missing[:5])
                + ('…' if len(missing) > 5 else '')
            )
        if partial:
            msg_parts.append(
                f'{len(partial)} partial fetch day(s): '
                + ', '.join(p['day'] for p in partial[:5])
                + ('…' if len(partial) > 5 else '')
            )
        mcp_partial = report.get('mcp_partial_count') or 0
        if mcp_partial:
            msg_parts.append(f'{mcp_partial} MCP source mismatch day(s)')
        if backlog > 0:
            msg_parts.append(f'{backlog:,} rows pending analysis')

        return {
            'ok': True,
            'start_date': start_s,
            'end_date': end_s,
            'missing_days': missing,
            'partial_days': partial,
            'refetch_days': refetch,
            'missing_count': len(missing),
            'partial_count': len(partial),
            'refetch_count': len(refetch),
            'mcp_partial_count': report.get('mcp_partial_count', 0),
            'mcp_partial_days': report.get('mcp_partial_days') or [],
            'pending_analysis_total': pending,
            'analysis_backlog_count': backlog,
            'daily': daily,
            'degraded': bool(missing or partial or backlog > 0 or mcp_partial),
            'message': '; '.join(msg_parts) if msg_parts else 'Coverage OK',
        }

    def _run_mcp_reconciliation(self, start_date: str, end_date: str) -> dict:
        """Query PS7 source and persist expected vs local counts."""
        sched = self.config.get('scheduler', {}) or {}
        mrc = sched.get('mcp_reconciliation') or {}
        if not isinstance(mrc, dict) or not mrc.get('enabled', True):
            return {'enabled': False}
        if not mrc.get('after_fetch', True):
            return {'enabled': True, 'skipped': True}

        scripts_path = str(Path(__file__).parent / 'scripts')
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from source_reconciliation import build_source_client, reconcile_day_range

        client = build_source_client(self.config)
        return reconcile_day_range(
            self.db, self.config, client, start_date, end_date,
        )

    def _get_refetch_days(self) -> list:
        """Calendar days needing fetch (zero-row gaps + partial-volume days)."""
        health = self.compute_coverage_health()
        days = [d['day'] for d in (health.get('refetch_days') or [])]
        if days:
            return days
        return self._get_missing_fetch_days()

    def _get_missing_fetch_days(self) -> list:
        sched = self.config.get('scheduler', {}) or {}
        ca = sched.get('coverage_audit') or {}
        lookback = int(ca.get('lookback_days', 14) or 14)
        end = datetime.now().date()
        start = end - timedelta(days=max(1, lookback) - 1)
        scripts_path = str(Path(__file__).parent / 'scripts')
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from coverage_audit import detect_missing_fetch_days

        report = detect_missing_fetch_days(
            self.db,
            start.strftime('%Y-%m-%d'),
            end.strftime('%Y-%m-%d'),
            min_neighbor_rows=int(ca.get('min_neighbor_rows', 1000) or 1000),
        )
        return [m['day'] for m in (report.get('missing_days') or [])]

    def _fetch_missing_days(self, days: list):
        """Background fetch+analyze for explicit missing calendar days."""
        if not days:
            return
        t = threading.Thread(
            target=self._run_missing_days_fetch,
            kwargs={'days': list(days)},
            daemon=True,
            name='pipeline-missing-days',
        )
        t.start()

    def _run_missing_days_fetch(self, days: list):
        if not _coverage_fetch_busy.acquire(blocking=False):
            logger.info('Missing-day fetch skipped — already running')
            return
        try:
            for day in days:
                if not self._wait_for_vpn('catchup'):
                    logger.warning('Missing-day fetch stopped — VPN/API not ready (%s)', day)
                    break
                self._run_pipeline(
                    days_back=1,
                    trigger='catchup',
                    start_date=day,
                    end_date=day,
                    catchup_chunk={'index': 1, 'total': 1, 'day': day, 'reason': 'missing_fetch'},
                )
        finally:
            _coverage_fetch_busy.release()

    def _vpn_probe_configured(self) -> bool:
        sched = self.config.get('scheduler', {}) or {}
        if str(sched.get('vpn_probe_url') or '').strip():
            return True
        return bool(sched.get('vpn_use_api_probe', True) and self.api_client)

    def _vpn_probe_required_for(self, trigger: str) -> bool:
        if not self._vpn_probe_configured():
            return False
        sched = self.config.get('scheduler', {}) or {}
        raw_triggers = sched.get('vpn_probe_triggers', ['scheduled', 'catchup'])
        if isinstance(raw_triggers, str):
            triggers = [t.strip() for t in raw_triggers.split(',') if t.strip()]
        else:
            triggers = list(raw_triggers)
        return trigger in triggers

    def _wait_for_vpn(self, trigger: str) -> bool:
        """Retry VPN/API probe until success or max wait — for boot+VPN delay."""
        global _vpn_wait_status
        if not self._vpn_probe_required_for(trigger):
            _vpn_wait_status = {'status': 'not_required', 'trigger': trigger}
            return True

        sched = self.config.get('scheduler', {}) or {}
        interval = float(sched.get('vpn_probe_retry_interval_seconds', 60) or 60)
        interval = max(5.0, min(interval, 600.0))
        max_min = float(sched.get('vpn_probe_retry_max_minutes', 15) or 15)
        max_min = max(1.0, min(max_min, 120.0))
        deadline = time.time() + max_min * 60.0
        attempts = 0

        while time.time() < deadline:
            attempts += 1
            if self._vpn_probe_passes(trigger):
                _vpn_wait_status = {
                    'status': 'ready',
                    'trigger': trigger,
                    'attempts': attempts,
                    'checked_at': datetime.now().isoformat(timespec='seconds'),
                }
                return True
            remaining = max(0, int(deadline - time.time()))
            logger.info(
                'VPN/API not ready (trigger=%s) — retry in %ss (%ss left)',
                trigger,
                int(interval),
                remaining,
            )
            _vpn_wait_status = {
                'status': 'waiting',
                'trigger': trigger,
                'attempts': attempts,
                'seconds_remaining': remaining,
            }
            time.sleep(interval)

        _vpn_wait_status = {
            'status': 'timeout',
            'trigger': trigger,
            'attempts': attempts,
            'checked_at': datetime.now().isoformat(timespec='seconds'),
        }
        return False

    def _vpn_probe_passes(self, trigger: str) -> bool:
        """If vpn_probe_url or API probe is configured, require success before runs."""
        if not self._vpn_probe_required_for(trigger):
            return True

        sched = self.config.get('scheduler', {}) or {}
        url = (sched.get('vpn_probe_url') or '').strip()
        timeout = float(sched.get('vpn_probe_timeout', 8) or 8)
        timeout = max(1.0, min(timeout, 120.0))

        if url:
            method = str(sched.get('vpn_probe_method', 'get') or 'get').lower()
            if method not in ('get', 'head'):
                method = 'get'
            try:
                import requests
            except ImportError:
                logger.warning('VPN probe skipped: requests not installed')
                return True
            try:
                fn = requests.head if method == 'head' else requests.get
                resp = fn(url, timeout=timeout, allow_redirects=True)
            except requests.RequestException as e:
                logger.warning('VPN probe request failed: %s', e)
                return False
            custom_ok = sched.get('vpn_probe_ok_status_codes')
            if custom_ok is not None:
                try:
                    codes = set(
                        int(x) for x in custom_ok
                        if str(x).strip() not in ('', 'None')
                    )
                except (TypeError, ValueError):
                    codes = {200}
                ok = resp.status_code in codes
            else:
                ok = 200 <= resp.status_code < 400
            if not ok:
                logger.warning(
                    'VPN probe %s returned HTTP %s (expected success per config)',
                    url,
                    resp.status_code,
                )
            return ok

        if sched.get('vpn_use_api_probe', True) and self.api_client:
            ok = bool(self.api_client.probe_connectivity(timeout=timeout))
            if not ok:
                logger.warning('Affiliate API probe (a=me) failed — VPN likely not connected')
            return ok

        return True

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _check_apscheduler() -> bool:
        try:
            import apscheduler  # noqa: F401
            return True
        except ImportError:
            return False

    def _register_job(self, cfg: dict):
        from apscheduler.triggers.cron import CronTrigger
        self._scheduler.add_job(
            self._run_pipeline,
            CronTrigger(hour=cfg.get('hour', 14), minute=cfg.get('minute', 0)),
            id='fetch_and_analyze',
            replace_existing=True,
            kwargs={'days_back': cfg.get('days_back', 1), 'trigger': 'scheduled'},
        )

    def _register_enrich_backlog_job(self):
        """Register (or remove) the interval job that drains unenriched fraud_results."""
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job('enrich_backlog')
        except Exception:
            pass

        sched_cfg = self.config.get('scheduler', {}) or {}
        eb = sched_cfg.get('enrich_backlog')
        if not isinstance(eb, dict):
            eb = {}
        if not eb.get('enabled', True):
            logger.info('Scheduled enrich backlog job disabled')
            return

        admin_user, _admin_pass = self.config.get_admin_api_credentials()
        if not admin_user:
            logger.info(
                'Enrich backlog job not scheduled — configure admin API credentials '
                '(Settings) to enable automatic enrichment draining'
            )
            return

        interval = max(1, min(int(eb.get('interval_minutes', 15) or 15), 24 * 60))
        try:
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler.add_job(
                self._run_enrich_backlog,
                IntervalTrigger(minutes=interval),
                id='enrich_backlog',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )
            logger.info('Scheduled enrich backlog job every %s minute(s)', interval)
        except Exception as e:
            logger.error('Could not register enrich backlog job: %s', e, exc_info=True)

    def _run_enrich_backlog(self):
        """APScheduler callback: process a batch of unenriched DUIDs (global backlog)."""
        global _current_enrich_backlog

        if not _enrich_backlog_busy.acquire(blocking=False):
            logger.debug('Enrich backlog skipped — already running')
            return

        try:
            with _run_lock:
                if _current_run.get('status') == 'running':
                    logger.info('Enrich backlog skipped — pipeline run in progress')
                    return

            sched_cfg = self.config.get('scheduler', {}) or {}
            eb = sched_cfg.get('enrich_backlog')
            if not isinstance(eb, dict):
                eb = {}
            if not eb.get('enabled', True):
                return

            admin_user, admin_pass = self.config.get_admin_api_credentials()
            if not admin_user or not admin_pass:
                return

            batch = max(1, min(int(eb.get('batch_limit', 2000) or 2000), 50_000))
            throttle = float(eb.get('throttle_seconds', 0.25) or 0)
            throttle = max(0.0, min(throttle, 60.0))

            scripts_path = str(Path(__file__).parent / 'scripts')
            if scripts_path not in sys.path:
                sys.path.insert(0, scripts_path)
            from admin_api_client import AdminAPIClient
            from admin_enricher import AdminEnricher

            enricher = AdminEnricher(
                db=self.db,
                client=AdminAPIClient(admin_user, admin_pass),
                config=self.config,
                throttle=throttle,
            )
            summary = enricher.run(limit=batch, since_analyzed_at=None)

            snap = {
                'completed_at': datetime.now().isoformat(timespec='seconds'),
            }
            for k in (
                'total', 'enriched', 'unavailable', 'skipped', 'errors',
                'discover_concentration_flagged',
            ):
                if k in summary:
                    snap[k] = summary[k]
            if summary.get('error'):
                snap['error'] = summary['error']
            _current_enrich_backlog = snap

            if summary.get('error'):
                logger.warning('Enrich backlog: %s', summary.get('error'))
            else:
                logger.info(
                    'Enrich backlog: enriched=%s unavailable=%s errors=%s (batch %s)',
                    summary.get('enriched', 0),
                    summary.get('unavailable', 0),
                    summary.get('errors', 0),
                    summary.get('total', 0),
                )
        except Exception as exc:
            logger.warning('Enrich backlog failed: %s', exc, exc_info=True)
        finally:
            _enrich_backlog_busy.release()

    def _register_coverage_audit_job(self):
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job('coverage_audit')
        except Exception:
            pass

        sched_cfg = self.config.get('scheduler', {}) or {}
        ca = sched_cfg.get('coverage_audit')
        if not isinstance(ca, dict):
            ca = {}
        if not ca.get('enabled', True):
            logger.info('Coverage audit job disabled')
            return

        hours = max(1, min(int(ca.get('interval_hours', 6) or 6), 168))
        try:
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler.add_job(
                self._run_coverage_audit,
                IntervalTrigger(hours=hours),
                id='coverage_audit',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=7200,
            )
            logger.info('Scheduled coverage audit every %s hour(s)', hours)
        except Exception as e:
            logger.error('Could not register coverage audit job: %s', e, exc_info=True)

    def _run_coverage_audit(self):
        global _current_coverage_audit
        try:
            health = self.compute_coverage_health()
            snap = {
                'completed_at': datetime.now().isoformat(timespec='seconds'),
                **{k: health.get(k) for k in (
                    'missing_count', 'missing_days', 'pending_analysis_total',
                    'analysis_backlog_count', 'degraded', 'message',
                )},
            }
            _current_coverage_audit = snap

            missing_days = [m['day'] for m in (health.get('refetch_days') or health.get('missing_days') or [])]
            if missing_days:
                logger.warning(
                    'Coverage audit: %s day(s) need refetch: %s',
                    len(missing_days),
                    missing_days,
                )
                sched = self.config.get('scheduler', {}) or {}
                ca = sched.get('coverage_audit') or {}
                if ca.get('auto_fetch_missing', True) and self.api_client:
                    if self._should_notify_macos():
                        self._notify_macos(
                            'Fraud pipeline — missing dates',
                            f'Auto-fetch queued for {len(missing_days)} day(s).',
                        )
                    self._fetch_missing_days(missing_days)
            elif health.get('degraded'):
                logger.info('Coverage audit: %s', health.get('message'))
            else:
                logger.debug('Coverage audit: OK')
        except Exception as exc:
            logger.warning('Coverage audit failed: %s', exc, exc_info=True)
            _current_coverage_audit = {
                'completed_at': datetime.now().isoformat(timespec='seconds'),
                'error': str(exc),
            }

    def _register_analysis_backlog_job(self):
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job('analysis_backlog')
        except Exception:
            pass

        sched_cfg = self.config.get('scheduler', {}) or {}
        ab = sched_cfg.get('analysis_backlog')
        if not isinstance(ab, dict):
            ab = {}
        if not ab.get('enabled', True):
            logger.info('Analysis backlog job disabled')
            return

        interval = max(5, min(int(ab.get('interval_minutes', 20) or 20), 24 * 60))
        try:
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler.add_job(
                self._run_analysis_backlog,
                IntervalTrigger(minutes=interval),
                id='analysis_backlog',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )
            logger.info('Scheduled analysis backlog drain every %s minute(s)', interval)
        except Exception as e:
            logger.error('Could not register analysis backlog job: %s', e, exc_info=True)

    def _run_analysis_backlog(self):
        global _current_analysis_backlog

        with _run_lock:
            if _current_run.get('status') == 'running':
                logger.debug('Analysis backlog skipped — pipeline running')
                return

        sched_cfg = self.config.get('scheduler', {}) or {}
        ab = sched_cfg.get('analysis_backlog') or {}
        if not isinstance(ab, dict) or not ab.get('enabled', True):
            return

        lookback = int(ab.get('lookback_days', 14) or 14)
        batch = max(100, min(int(ab.get('batch_limit', 5000) or 5000), 50_000))
        priority = str(ab.get('priority', 'recent') or 'recent').strip().lower()
        paid_first = ab.get('paid_first', True) is not False
        pending_total = self.db.get_analysis_backlog_count(lookback_days=lookback)
        if pending_total < 1:
            _current_analysis_backlog = {
                'completed_at': datetime.now().isoformat(timespec='seconds'),
                'pending_total': 0,
                'analyzed': 0,
            }
            return

        day = self.db.get_priority_unanalyzed_day(
            lookback_days=lookback,
            priority=priority,
        )
        if not day:
            return

        scripts_path = str(Path(__file__).parent / 'scripts')
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from pipeline_analysis import drain_unanalyzed_for_day

        try:
            summary = drain_unanalyzed_for_day(
                self.db,
                self.config,
                day,
                batch_limit=batch,
                max_batches=1,
                paid_first=paid_first,
            )
            analyzed = int(summary.get('analyzed') or 0)
            high_risk = int(summary.get('high_risk') or 0)

            snap = {
                'completed_at': datetime.now().isoformat(timespec='seconds'),
                'day': day,
                'priority': priority,
                'analyzed': analyzed,
                'high_risk': high_risk,
                'remaining_day': int(summary.get('remaining') or 0),
                'pending_total': pending_total,
            }
            _current_analysis_backlog = snap
            if analyzed:
                logger.info(
                    'Analysis backlog: day=%s priority=%s analyzed=%s high_risk=%s pending≈%s',
                    day, priority, analyzed, high_risk, pending_total,
                )
        except Exception as exc:
            logger.warning('Analysis backlog drain failed: %s', exc, exc_info=True)
            _current_analysis_backlog = {
                'completed_at': datetime.now().isoformat(timespec='seconds'),
                'error': str(exc),
                'day': day,
            }

    @staticmethod
    def _parse_ts_loose(s):
        """Parse ISO timestamps from DB / APScheduler; return naive local datetime."""
        if s is None:
            return None
        s = str(s).strip()
        if not s:
            return None
        s = s.replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt

    def _scheduled_health(self, sched_cfg: dict, next_run_iso, embedded_skipped: bool):
        """
        Surface missed scheduled runs in the dashboard when scheduling is enabled.
        """
        empty = {
            'stale': False,
            'reason': None,
            'message': None,
            'last_scheduled_completed_at': None,
        }
        if not sched_cfg.get('enabled', False):
            return {**empty, 'reason': 'disabled'}

        if embedded_skipped:
            return {
                'stale': False,
                'reason': 'standalone_expected',
                'message': None,
                'last_scheduled_completed_at': None,
            }

        if not self._available:
            return {**empty, 'reason': 'no_apscheduler'}

        if not (self._scheduler and self._scheduler.running):
            return {
                'stale': True,
                'reason': 'scheduler_not_running',
                'message': (
                    'Scheduling is enabled but the embedded scheduler is not running. '
                    'Restart the web app or run `python scheduler.py` with SKIP_EMBEDDED_SCHEDULER=1 on the app.'
                ),
                'last_scheduled_completed_at': None,
            }

        with _run_lock:
            if _current_run.get('status') == 'running':
                return {
                    'stale': False,
                    'reason': 'pipeline_running',
                    'message': None,
                    'last_scheduled_completed_at': None,
                }

        last_at, last_dt, last_run_type = self._last_effective_pipeline_completion(sched_cfg)
        now = datetime.now()
        stale = False
        reason = None
        message = None

        stale_after_h = float(sched_cfg.get('stale_after_hours', 80))
        GRACE_AFTER_DUE_H = 2

        if last_dt and (now - last_dt) > timedelta(hours=stale_after_h):
            stale = True
            reason = 'last_success_too_old'
            hours = (now - last_dt).total_seconds() / 3600
            max_days = int(sched_cfg.get('startup_catchup_max_days', 31))
            if sched_cfg.get('startup_catchup', True) and hours <= max_days * 24:
                message = (
                    f'No pipeline completed in ~{hours:.0f}h '
                    f'(last {last_run_type or "run"} {last_at}). '
                    f'Expected when the app or PC was off — startup catch-up backfills up to '
                    f'{max_days} day(s) automatically.'
                )
            else:
                message = (
                    f'No successful pipeline in ~{hours:.0f}h '
                    f'(last completed {last_at}). '
                    'Run catch-up from Scheduler settings or check that the app stays running at the scheduled time.'
                )
        elif not last_dt:
            next_dt = self._parse_ts_loose(next_run_iso)
            if next_dt and now > next_dt + timedelta(hours=GRACE_AFTER_DUE_H):
                stale = True
                reason = 'no_completed_after_due'
                if sched_cfg.get('startup_catchup', True):
                    message = (
                        'Scheduling is on, but no completed pipeline run is recorded yet. '
                        'If the app or PC was off at run time, startup catch-up will backfill on launch.'
                    )
                else:
                    message = (
                        'Scheduling is on, but no completed scheduled run is recorded after the latest due window. '
                        'If the app or PC was off at run time, the job will not have executed.'
                    )

        return {
            'stale': stale,
            'reason': reason,
            'message': message,
            'last_scheduled_completed_at': last_at,
        }

    def _last_effective_pipeline_completion(self, sched_cfg: dict):
        """Most recent completed scheduled run; include catch-up when startup_catchup is on."""
        sched_row = self.db.get_last_pipeline_run(run_type='scheduled', status='completed')
        sched_at = sched_row.get('completed_at') if sched_row else None
        sched_dt = self._parse_ts_loose(sched_at)

        if not sched_cfg.get('startup_catchup', True):
            return sched_at, sched_dt, 'scheduled'

        catch_row = self.db.get_last_pipeline_run(run_type='catchup', status='completed')
        catch_at = catch_row.get('completed_at') if catch_row else None
        catch_dt = self._parse_ts_loose(catch_at)

        if catch_dt and (not sched_dt or catch_dt > sched_dt):
            return catch_at, catch_dt, 'catchup'
        return sched_at, sched_dt, 'scheduled'

    # ── Core pipeline ──────────────────────────────────────────────────────────

    def _run_pipeline(
        self,
        days_back: int = 1,
        trigger: str = 'scheduled',
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        catchup_chunk: Optional[dict] = None,
    ):
        """
        The full fetch → preprocess → analyze pipeline.
        Mirrors the dashboard's manual fetch + analyze flow exactly.
        Stores a config snapshot for ML lineage.
        """
        global _current_run

        acquired = _pipeline_busy.acquire(blocking=False)
        if not acquired:
            logger.warning(
                "Pipeline skipped: another run is already in progress "
                f"(trigger={trigger!r})"
            )
            return

        stale_hours = float((self.config.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
        lock_holder = f"scheduler-{os.getpid()}-{trigger}"
        db_lock = False
        try:
            db_lock = self.db.try_acquire_named_lock(
                'pipeline',
                lock_holder,
                stale_hours=stale_hours,
                meta={'source': trigger},
            )
        except Exception as e:
            logger.warning('Named pipeline lock acquire failed: %s', e)
            _pipeline_busy.release()
            return
        if not db_lock:
            logger.warning(
                "Pipeline skipped: DB job lock held "
                f"(trigger={trigger!r})"
            )
            _pipeline_busy.release()
            return

        try:
            if not self._wait_for_vpn(trigger):
                logger.warning(
                    'Pipeline skipped (trigger=%s): VPN / API not ready after retries',
                    trigger,
                )
                try:
                    if self._should_notify_macos():
                        self._notify_macos(
                            'Fraud pipeline skipped',
                            'VPN/API not ready — connect VPN; catch-up will retry automatically.',
                        )
                except Exception:
                    pass
                return

            run_id     = str(uuid.uuid4())[:8]
            started_at = datetime.now()
            if start_date and end_date:
                pass  # explicit window (catch-up chunk)
            else:
                end_date = started_at.strftime('%Y-%m-%d')
                start_date = (started_at - timedelta(days=days_back)).strftime('%Y-%m-%d')

            chunk_label = ''
            if catchup_chunk:
                chunk_label = (
                    f" (catch-up day {catchup_chunk.get('index')}/"
                    f"{catchup_chunk.get('total')})"
                )

            # Config snapshot for reproducibility / future ML training
            config_snapshot = {
                'schema_version':     '1.0',
                'days_back':          days_back,
                'min_duid_threshold': self.config.get('min_duid_threshold', 0),
                'house_affiliates':   self.config.get_house_affiliates(),
                'risk_thresholds': {
                    'high':   int(self.config.get_risk_threshold('high') or 50),
                    'medium': int(self.config.get_risk_threshold('medium') or 25),
                },
                'triggered_by':       trigger,
            }
            if catchup_chunk:
                config_snapshot['catchup_chunk'] = catchup_chunk

            with _run_lock:
                _current_run = {
                    'run_id':     run_id,
                    'status':     'running',
                    'trigger':    trigger,
                    'started':    started_at.isoformat(),
                    'progress':   0,
                    'step':       f'Starting…{chunk_label}',
                    'date_range': f'{start_date} → {end_date}',
                }

            self.db.record_pipeline_run(
                run_id=run_id, run_type=trigger, status='running',
                started_at=started_at, date_range_start=start_date,
                date_range_end=end_date, config_snapshot=config_snapshot,
            )

            total_fetched  = 0
            total_analyzed = 0
            high_risk      = 0

            try:
                # ── Step 1: Fetch ─────────────────────────────────────────────────
                self._update_run(progress=5, step='Fetching data…')

                if not self.api_client:
                    raise RuntimeError("API client not configured — set API key in Settings")

                for i, data_type in enumerate(['free', 'paid']):
                    self._update_run(
                        progress=5 + i * 20,
                        step=f'Fetching {data_type} records ({start_date} → {end_date})…',
                    )
                    records = self.api_client.fetch_data(data_type, start_date, end_date)
                    if records:
                        if data_type == 'paid':
                            inserted, duplicates = self.db.insert_paid_records(records)
                        else:
                            inserted, duplicates = self.db.insert_free_records(records)
                        self.db.record_fetch(
                            data_type,
                            start_date,
                            end_date,
                            inserted,
                            records_returned=len(records),
                            records_duplicates=duplicates,
                        )
                        total_fetched += inserted
                        logger.info(f"[{run_id}] Fetched {data_type}: "
                                    f"{len(records)} records, {inserted} new")

                # ── Step 1b: MCP / PS7 source reconciliation ─────────────────────
                mrc = (self.config.get('scheduler', {}) or {}).get('mcp_reconciliation') or {}
                recon_summary = None
                if isinstance(mrc, dict) and mrc.get('enabled', True) and mrc.get('after_fetch', True):
                    self._update_run(progress=48, step='Reconciling source counts…')
                    try:
                        recon_summary = self._run_mcp_reconciliation(start_date, end_date)
                        config_snapshot['mcp_reconciliation'] = {
                            'days_checked': len((recon_summary or {}).get('days') or []),
                            'enabled': True,
                        }
                    except Exception as exc:
                        logger.warning('[%s] MCP reconciliation failed: %s', run_id, exc)
                        config_snapshot['mcp_reconciliation'] = {
                            'enabled': True,
                            'error': str(exc),
                        }

                block_on_partial = bool(mrc.get('block_analysis_on_partial', False))
                if block_on_partial and recon_summary:
                    partial_days = [
                        d['day'] for d in (recon_summary.get('days') or [])
                        if d.get('reconciliation_status') in ('partial', 'missing')
                    ]
                    if partial_days:
                        raise RuntimeError(
                            f'MCP reconciliation partial for: {", ".join(partial_days[:5])}'
                        )

                # ── Step 2: Preprocess + Analyze (shared pipeline) ────────────────
                self._update_run(progress=50, step='Loading analysis modules…')

                scripts_path = str(Path(__file__).parent / 'scripts')
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)

                import pandas as pd
                import sqlite3
                from pipeline_analysis import analyze_dataframe

                min_duid = int(self.config.get('min_duid_threshold', 0) or 0)
                high_th = int(self.config.get_risk_threshold('high') or 50)
                skip_codes = self.config.get_affiliate_analysis_skip_codes_lower(
                    include_house_in_analysis=False
                )

                for type_idx, data_type in enumerate(['free', 'paid']):
                    self._update_run(
                        progress=55 + type_idx * 20,
                        step=f'Analyzing {data_type} records…',
                    )

                    with sqlite3.connect(self.db.db_path) as conn:
                        df = pd.read_sql_query(
                            f"SELECT * FROM {data_type} WHERE {Database.SQL_TRANS_DATE_BETWEEN}",  # noqa: S608
                            conn, params=[start_date, end_date],
                        )

                    if df.empty:
                        continue

                    summary = analyze_dataframe(
                        self.db,
                        self.config,
                        data_type,
                        df,
                        min_duid=min_duid,
                        skip_affiliate_codes=skip_codes,
                        mark_skipped_analyzed=True,
                    )
                    analyzed_n = int(summary.get('analyzed') or 0)
                    high_n = int(summary.get('high_risk') or 0)
                    total_analyzed += analyzed_n
                    high_risk += high_n
                    logger.info(
                        f"[{run_id}] Analyzed {data_type}: {analyzed_n} records, "
                        f"{high_n} high-risk (threshold={high_th})"
                    )

                # ── Step 2b: Immediate drain for remaining unanalyzed rows in window ──
                sched_cfg = self.config.get('scheduler', {}) or {}
                if sched_cfg.get('immediate_drain_after_fetch', True):
                    drain_batch = int(
                        sched_cfg.get('immediate_drain_batch_limit')
                        or sched_cfg.get('analysis_backlog', {}).get('batch_limit')
                        or 5000
                    )
                    drain_batches = int(sched_cfg.get('immediate_drain_max_batches', 20) or 20)
                    paid_first = (
                        sched_cfg.get('analysis_backlog', {}).get('paid_first', True) is not False
                    )
                    self._update_run(progress=88, step='Draining pending analysis…')
                    if scripts_path not in sys.path:
                        sys.path.insert(0, scripts_path)
                    from pipeline_analysis import drain_unanalyzed_for_range

                    drain_summary = drain_unanalyzed_for_range(
                        self.db,
                        self.config,
                        start_date,
                        end_date,
                        batch_limit=drain_batch,
                        max_batches=drain_batches,
                        paid_first=paid_first,
                    )
                    drained = int(drain_summary.get('analyzed') or 0)
                    drain_high = int(drain_summary.get('high_risk') or 0)
                    if drained:
                        total_analyzed += drained
                        high_risk += drain_high
                        logger.info(
                            f"[{run_id}] Immediate drain: {drained} analyzed, "
                            f"{drain_high} high-risk ({start_date} → {end_date})"
                        )
                    config_snapshot['immediate_drain'] = {
                        'analyzed': drained,
                        'high_risk': drain_high,
                        'days': drain_summary.get('days') or [],
                    }

                # ── Step 3: Quick admin enrichment (this run only; backlog via enrich_backlog job)
                enrich_summary = None
                sched_cfg = self.config.get('scheduler', {}) or {}
                fresh_lim = int(
                    sched_cfg.get('enrich_fresh_limit')
                    or sched_cfg.get('enrich_limit')
                    or 500
                )
                fresh_lim = max(0, min(fresh_lim, 50_000))
                skip_enrich = (
                    trigger == 'catchup'
                    and sched_cfg.get('catchup_skip_enrichment', True)
                )
                if skip_enrich:
                    logger.info(
                        f"[{run_id}] Skipping post-pipeline enrichment "
                        "(catch-up — enrich_backlog job will drain)"
                    )
                    config_snapshot['enrichment_skipped'] = 'catchup'
                elif fresh_lim > 0 and sched_cfg.get('enrich_after_pipeline', True):
                    admin_user, admin_pass = self.config.get_admin_api_credentials()
                    if admin_user and admin_pass:
                        self._update_run(progress=92, step='Admin enrichment (fresh)…')
                        try:
                            if scripts_path not in sys.path:
                                sys.path.insert(0, scripts_path)
                            from admin_api_client import AdminAPIClient
                            from admin_enricher import AdminEnricher

                            enricher = AdminEnricher(
                                db=self.db,
                                client=AdminAPIClient(admin_user, admin_pass),
                                config=self.config,
                            )
                            since_run = started_at.strftime('%Y-%m-%d %H:%M:%S')
                            enrich_summary = enricher.run(
                                limit=fresh_lim,
                                since_analyzed_at=since_run,
                            )
                            if enrich_summary.get('error'):
                                logger.warning(
                                    f"[{run_id}] Fresh enrichment: {enrich_summary.get('error')}"
                                )
                            else:
                                n = enrich_summary.get('total', 0)
                                note = ''
                                if n >= fresh_lim:
                                    note = ' (cap hit — remainder via enrich_backlog job)'
                                logger.info(
                                    f"[{run_id}] Fresh enrichment: enriched="
                                    f"{enrich_summary.get('enriched', 0)}, "
                                    f"errors={enrich_summary.get('errors', 0)}, "
                                    f"discover_concentration_flagged="
                                    f"{enrich_summary.get('discover_concentration_flagged', 0)}"
                                    f"{note}"
                                )
                        except Exception as exc:
                            logger.warning(
                                f"[{run_id}] Post-pipeline enrichment failed: {exc}",
                                exc_info=True,
                            )
                    else:
                        logger.info(
                            f"[{run_id}] Skipping post-pipeline enrichment "
                            "(admin API credentials not configured)"
                        )

                # ── Complete ──────────────────────────────────────────────────────
                duration = (datetime.now() - started_at).total_seconds()
                if enrich_summary and not enrich_summary.get('error'):
                    snap_keys = (
                        'total', 'enriched', 'skipped', 'errors',
                        'discover_concentration_flagged',
                    )
                    config_snapshot = {
                        **config_snapshot,
                        'enrichment': {
                            k: enrich_summary[k]
                            for k in snap_keys
                            if k in enrich_summary
                        },
                    }
                self.db.record_pipeline_run(
                    run_id=run_id, run_type=trigger, status='completed',
                    started_at=started_at, completed_at=datetime.now(),
                    duration_seconds=duration, records_fetched=total_fetched,
                    records_analyzed=total_analyzed, high_risk_found=high_risk,
                    config_snapshot=config_snapshot, date_range_start=start_date,
                    date_range_end=end_date,
                )

                with _run_lock:
                    _current_run = {
                        'run_id':          run_id,
                        'status':          'completed',
                        'trigger':         trigger,
                        'started':         started_at.isoformat(),
                        'completed':       datetime.now().isoformat(),
                        'progress':        100,
                        'step':            'Done',
                        'records_fetched': total_fetched,
                        'records_analyzed':total_analyzed,
                        'high_risk_found': high_risk,
                        'duration_s':      round(duration, 1),
                    }

                logger.info(f"[{run_id}] Pipeline complete — "
                            f"{total_analyzed} analyzed, {high_risk} high-risk, "
                            f"{duration:.1f}s")

            except Exception as exc:
                duration = (datetime.now() - started_at).total_seconds()
                logger.error(f"[{run_id}] Pipeline failed: {exc}", exc_info=True)
                try:
                    if self._should_notify_macos():
                        msg = ' '.join(str(exc).split())[:500]
                        self._notify_macos('Fraud pipeline failed', msg)
                except Exception:
                    pass

                self.db.record_pipeline_run(
                    run_id=run_id, run_type=trigger, status='failed',
                    started_at=started_at, completed_at=datetime.now(),
                    duration_seconds=duration, records_fetched=total_fetched,
                    records_analyzed=total_analyzed, high_risk_found=high_risk,
                    error_message=str(exc), config_snapshot=config_snapshot,
                    date_range_start=start_date, date_range_end=end_date,
                )

                with _run_lock:
                    _current_run = {
                        'run_id':  run_id,
                        'status':  'failed',
                        'trigger': trigger,
                        'started': started_at.isoformat(),
                        'progress': 0,
                        'step':    f'Error: {exc}',
                        'error':   str(exc),
                    }
        finally:
            try:
                self.db.release_named_lock('pipeline', lock_holder)
            except Exception as lock_err:
                logger.warning('Failed to release pipeline named lock: %s', lock_err)
            _pipeline_busy.release()

    def _update_run(self, progress: int, step: str):
        with _run_lock:
            _current_run['progress'] = progress
            _current_run['step']     = step


if __name__ == '__main__':
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from logging_config import configure_logging

    configure_logging('fraud-detection-scheduler')

    from config import Config
    from api_client import APIClient

    _cfg = Config()
    _db_path = os.environ.get('DB_PATH') or _cfg.get('database_path', 'affiliate_data.db')
    _db = Database(_db_path)
    try:
        _stale = float((_cfg.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
        _n = _db.fail_stale_pipeline_runs(stale_hours=_stale)
        if _n:
            logger.info('Standalone scheduler boot: cleared %s stale pipeline_runs', _n)
    except Exception as _e:
        logger.warning('Standalone scheduler boot fail_stale: %s', _e)
    _key = _cfg.get_api_key()
    _api = APIClient(_key) if _key else None
    if not _api:
        logger.warning(
            'No affiliate API key configured — pipeline fetch will fail until '
            'Settings are saved or FRAUD_DETECTION_API_KEY is set.'
        )

    _sched = FraudPipelineScheduler(_db, _cfg, _api)
    _sched.start()
    logger.info(
        'Standalone scheduler process running (config from config.json). '
        'Stop with Ctrl+C. Use SKIP_EMBEDDED_SCHEDULER=1 on the web app to avoid duplicate schedulers.'
    )
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info('Scheduler shutting down…')
        _sched.stop()
