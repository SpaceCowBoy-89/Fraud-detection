"""Scheduler reliability: VPN wait, coverage health, missing-day fetch."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import scheduler as sched_mod
from scheduler import FraudPipelineScheduler


@pytest.fixture
def scheduler():
    db = MagicMock()
    cfg = {
        'scheduler': {
            'vpn_use_api_probe': True,
            'vpn_probe_triggers': ['scheduled', 'catchup'],
            'vpn_probe_retry_interval_seconds': 0.01,
            'vpn_probe_retry_max_minutes': 0.001,
            'coverage_audit': {
                'enabled': True,
                'lookback_days': 7,
                'min_neighbor_rows': 100,
            },
        },
        'min_duid_threshold': 0,
        'risk_thresholds': {'high': 50, 'medium': 25},
    }
    config = MagicMock()
    config.config = cfg
    config.get.side_effect = lambda k, default=None: cfg.get(k, default)

    api = MagicMock()
    api.probe_connectivity.return_value = False

    s = FraudPipelineScheduler(db=db, config=config, api_client=api)
    s._available = True
    return s, db, api


def test_wait_for_vpn_times_out(scheduler):
    s, _db, api = scheduler
    api.probe_connectivity.return_value = False
    s.config.config['scheduler']['vpn_probe_retry_interval_seconds'] = 0.05
    s.config.config['scheduler']['vpn_probe_retry_max_minutes'] = 0.002
    with patch('scheduler.time.sleep'):
        assert s._wait_for_vpn('catchup') is False
    assert sched_mod._vpn_wait_status.get('status') == 'timeout'


def test_wait_for_vpn_succeeds_when_probe_ready(scheduler):
    s, _db, api = scheduler
    api.probe_connectivity.return_value = True
    assert s._wait_for_vpn('catchup') is True
    assert sched_mod._vpn_wait_status.get('status') == 'ready'


def test_pipeline_skips_after_vpn_timeout(scheduler):
    s, db, _api = scheduler
    busy = MagicMock()
    busy.acquire.return_value = True
    with patch.object(s, '_wait_for_vpn', return_value=False):
        with patch.object(sched_mod, '_pipeline_busy', busy):
            s._run_pipeline(trigger='scheduled', days_back=1)
    db.record_pipeline_run.assert_not_called()


def test_compute_coverage_health_degraded(scheduler):
    s, db, _api = scheduler
    db.get_daily_pipeline_coverage.return_value = [
        {'day': '2026-07-02', 'fetched_total': 5000, 'pending_analysis': 0,
         'free_count': 4000, 'paid_count': 1000, 'source_analyzed': 0},
        {'day': '2026-07-03', 'fetched_total': 0, 'pending_analysis': 0,
         'free_count': 0, 'paid_count': 0, 'source_analyzed': 0},
        {'day': '2026-07-04', 'fetched_total': 0, 'pending_analysis': 0,
         'free_count': 0, 'paid_count': 0, 'source_analyzed': 0},
        {'day': '2026-07-05', 'fetched_total': 6000, 'pending_analysis': 100,
         'free_count': 5000, 'paid_count': 1000, 'source_analyzed': 0},
    ]
    db.get_analysis_backlog_count.return_value = 100
    db.get_reconciliation_results.return_value = {}

    health = s.compute_coverage_health()
    assert health['degraded'] is True
    assert health['missing_count'] >= 1
    assert 'missing fetch day' in health['message'].lower()


def test_fetch_missing_days_queues_pipeline(scheduler):
    s, _db, _api = scheduler
    with patch.object(s, '_run_missing_days_fetch') as run_fetch:
        s._fetch_missing_days(['2026-07-03', '2026-07-04'])
        import time
        time.sleep(0.05)
    run_fetch.assert_called_once_with(days=['2026-07-03', '2026-07-04'])
