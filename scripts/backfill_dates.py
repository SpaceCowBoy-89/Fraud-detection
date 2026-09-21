#!/usr/bin/env python3
"""
Backfill missing/sparse calendar days: fetch → analyze → sequential rescore.

Uses the same pipeline as the scheduler for each day (unfiltered global fetch).

Usage:
    # Auto-detect sparse days in June 2026 and backfill
    python scripts/backfill_dates.py --auto-june-2026

    # Explicit dates
    python scripts/backfill_dates.py --dates 2026-06-25,2026-06-26,2026-06-27

    # Date range (one pipeline run per day)
    python scripts/backfill_dates.py --start 2026-06-25 --end 2026-06-27

    # Skip fetch, only analyze existing raw rows + rescore sequential
    python scripts/backfill_dates.py --dates 2026-06-24 --analyze-only
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api_client import APIClient  # noqa: E402
from config import Config  # noqa: E402
from database import Database  # noqa: E402
from scheduler import FraudPipelineScheduler  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)


def _analyze_date_range(db, config, start_date: str, end_date: str, *, unanalyzed_only: bool = False):
    """Run analysis on free+paid rows in trans_datetime range (no fetch)."""
    import sqlite3

    import pandas as pd

    scripts_dir = ROOT / 'scripts'
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from data_preprocessor import DataPreprocessor  # noqa: E402
    from email_fraud_detector import EmailFraudDetector  # noqa: E402

    preprocessor = DataPreprocessor()
    detector = EmailFraudDetector(config)
    house_set = config.get_affiliate_analysis_skip_codes_lower(include_house_in_analysis=False)
    min_duid = int(config.get('min_duid_threshold', 0) or 0)
    high_th = int(config.get_risk_threshold('high') or 50)
    total = 0

    for data_type in ('free', 'paid'):
        with sqlite3.connect(db.db_path) as conn:
            where = Database.SQL_TRANS_DATE_BETWEEN
            if unanalyzed_only:
                where = f"analyzed = 0 AND {where}"
            df = pd.read_sql_query(
                f"SELECT * FROM {data_type} WHERE {where}",  # noqa: S608
                conn,
                params=[start_date, end_date],
            )
        if df.empty:
            continue

        df, _ = preprocessor.preprocess_batch(df)
        df = detector.normalize_column_names(df)
        detector.build_repeated_word_map(df)
        detector.build_geographic_cluster_maps(df)
        detector.build_shared_ip_map(df, db=db)
        detector.build_ip_velocity_map(df, db=db)
        detector.build_gender_concentration_map(df)
        detector.build_sequential_email_map(df)
        detector.build_affiliate_domain_concentration_map(df)

        email_col = detector.column_map.get('email')
        if not email_col or email_col not in df.columns:
            continue

        results = []
        for _, row in df.iterrows():
            duid = detector.get_column(row, 'duid', None)
            if duid is None or str(duid).strip() == '':
                continue
            if min_duid and duid:
                try:
                    if int(duid) < min_duid:
                        continue
                except (ValueError, TypeError):
                    pass

            wm_code = detector.get_column(row, 'webmaster_code', None)
            if not wm_code:
                for col in ('webmaster_code', 'site_code'):
                    if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
                        wm_code = row[col]
                        break
            if house_set and wm_code and str(wm_code).lower() in house_set:
                continue

            email = row.get(email_col)
            if not email or str(email).lower() in ('', 'nan', 'none'):
                continue

            analysis = detector.analyze_email(
                email,
                trans_datetime=detector.get_column(row, 'trans_datetime', None),
                pov_verified=detector.get_column(row, 'pov_verified', None),
                pov_verified_time=detector.get_column(row, 'pov_verified_time', None),
                ip_address=detector.get_column(row, 'ip', None),
                user_agent=detector.get_column(row, 'custom_http_user_agent', None),
                first_name=detector.get_column(row, 'first_name', None),
                user1=detector.get_column(row, 'custom_u1', None) or detector.get_column(row, 'user1', None),
            )
            analysis['DUID'] = duid
            analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
            analysis['data_type'] = data_type
            analysis['webmaster_code'] = wm_code
            analysis['campaign'] = detector.get_column(row, 'campaign', None)
            analysis['ad_id'] = detector.get_column(row, 'ad_id', None)
            analysis['trans_datetime'] = detector.get_column(row, 'trans_datetime', None)
            analysis['geo_country'] = detector.get_column(row, 'geo_country', None) or analysis.get('geo_country')
            analysis['ip'] = detector.get_column(row, 'ip', None)
            analysis['first_name'] = detector.get_column(row, 'first_name', None)
            analysis['custom_u1'] = detector.get_column(row, 'custom_u1', None) or detector.get_column(row, 'user1', None)
            analysis['user_agent'] = detector.get_column(row, 'custom_http_user_agent', None)
            results.append(analysis)

        if results:
            detector.apply_gender_concentration_to_results(results)
            detector.apply_sequential_email_to_results(results)
            detector.apply_affiliate_domain_concentration_to_results(results)
            db.save_fraud_results(results)
            duids = [r['DUID'] for r in results if r.get('DUID') not in (None, '', 'N/A')]
            if duids:
                db.mark_as_analyzed(duids, data_type)
            total += len(results)
            logger.info(
                'Analyzed %s %s: %d records (%d high-risk)',
                start_date,
                data_type,
                len(results),
                sum(1 for r in results if r.get('risk_score', 0) >= high_th),
            )

    return total


def _run_pipeline_day(scheduler: FraudPipelineScheduler, day: str):
    """Blocking fetch+analyze for one calendar day."""
    scheduler._run_pipeline(
        days_back=1,
        trigger='backfill',
        start_date=day,
        end_date=day,
    )


def _auto_june_2026_sparse_days(db: Database):
    scripts_dir = ROOT / 'scripts'
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from coverage_audit import detect_sparse_days

    report = detect_sparse_days(db, '2026-06-01', '2026-06-30')
    return [s['day'] for s in report.get('sparse_days') or []]


def main():
    parser = argparse.ArgumentParser(description='Backfill sparse/missing calendar days')
    parser.add_argument('--db', default=str(ROOT / 'affiliate_data.db'))
    parser.add_argument('--config', default=str(ROOT / 'config.json'))
    parser.add_argument('--dates', default=None, help='Comma-separated YYYY-MM-DD')
    parser.add_argument('--start', default=None)
    parser.add_argument('--end', default=None)
    parser.add_argument('--auto-june-2026', action='store_true')
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--unanalyzed-only', action='store_true', help='With --analyze-only, skip already-analyzed rows')
    parser.add_argument('--skip-rescore', action='store_true')
    parser.add_argument('--stale-hours', type=float, default=6.0)
    parser.add_argument('--pause-seconds', type=float, default=2.0)
    args = parser.parse_args()

    db = Database(args.db)
    db.setup_database()

    stale = db.fail_stale_pipeline_runs(stale_hours=args.stale_hours)
    if stale:
        logger.info('Marked %d stale pipeline run(s) as failed', stale)

    if args.auto_june_2026:
        days = _auto_june_2026_sparse_days(db)
    elif args.dates:
        days = [d.strip() for d in args.dates.split(',') if d.strip()]
    elif args.start and args.end:
        start = datetime.strptime(args.start, '%Y-%m-%d').date()
        end = datetime.strptime(args.end, '%Y-%m-%d').date()
        days = []
        cur = start
        while cur <= end:
            days.append(cur.strftime('%Y-%m-%d'))
            cur += timedelta(days=1)
    else:
        parser.error('Provide --dates, --start/--end, or --auto-june-2026')

    logger.info('Backfill plan: %d day(s): %s', len(days), ', '.join(days))

    config = Config(args.config)
    api_key = config.get('api_key') or config.get_api_key()
    api_client = APIClient(api_key) if api_key else None
    if not args.analyze_only and not api_client:
        logger.error('No API key in config — use --analyze-only or set api_key')
        sys.exit(1)

    scheduler = FraudPipelineScheduler(db, config, api_client)

    for day in days:
        logger.info('=== Processing %s ===', day)
        if args.analyze_only:
            n = _analyze_date_range(
                db, config, day, day, unanalyzed_only=args.unanalyzed_only,
            )
            logger.info('Analyze-only %s: %d records', day, n)
        else:
            _run_pipeline_day(scheduler, day)
        if args.pause_seconds > 0:
            time.sleep(args.pause_seconds)

    if not args.skip_rescore:
        scripts_dir = ROOT / 'scripts'
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from email_fraud_detector import rescore_sequential_email_from_fraud_results_table  # noqa: E402

        out = rescore_sequential_email_from_fraud_results_table(db, config)
        logger.info(
            'Sequential rescore: updated=%s clusters=%s rows=%s',
            out.get('updated'),
            out.get('clusters_found'),
            out.get('rows_considered'),
        )

    # Post-run coverage for June if relevant
    if args.auto_june_2026 or (args.start and args.start.startswith('2026-06')):
        scripts_dir = ROOT / 'scripts'
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from coverage_audit import affiliate_coverage, detect_sparse_days

        cov = detect_sparse_days(db, '2026-06-01', '2026-06-30')
        marina = affiliate_coverage(db, 'marinagoodads', '2026-06-01', '2026-06-30')
        logger.info(
            'Post-backfill June: sparse_days=%d marinagoodads rows=%d analyzed=%d',
            len(cov.get('sparse_days') or []),
            marina.get('total_rows', 0),
            marina.get('total_analyzed', 0),
        )


if __name__ == '__main__':
    main()
