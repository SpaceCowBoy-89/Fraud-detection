"""Scheduler health / stale detection for weekend and catch-up gaps."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scheduler import FraudPipelineScheduler, _current_run, _run_lock


@pytest.fixture
def scheduler():
    db = MagicMock()
    sched = FraudPipelineScheduler(db=db, config={}, api_client=MagicMock())
    sched._available = True
    sched._scheduler = MagicMock()
    sched._scheduler.running = True
    return sched, db


def _sched_cfg(**overrides):
    base = {
        'enabled': True,
        'startup_catchup': True,
        'startup_catchup_max_days': 31,
        'stale_after_hours': 80,
    }
    base.update(overrides)
    return base


def test_recent_catchup_clears_stale(scheduler):
    sched, db = scheduler
    recent = (datetime.now() - timedelta(hours=2)).isoformat()
    old = (datetime.now() - timedelta(days=5)).isoformat()

    def fake_last(run_type=None, status=None):
        if run_type == 'scheduled' and status == 'completed':
            return {'completed_at': old, 'run_type': 'scheduled'}
        if run_type == 'catchup' and status == 'completed':
            return {'completed_at': recent, 'run_type': 'catchup'}
        return None

    db.get_last_pipeline_run.side_effect = fake_last
    health = sched._scheduled_health(_sched_cfg(), next_run_iso=None, embedded_skipped=False)
    assert health['stale'] is False


def test_weekend_gap_within_threshold_not_stale(scheduler):
    sched, db = scheduler
    last = (datetime.now() - timedelta(hours=70)).isoformat()
    db.get_last_pipeline_run.return_value = {'completed_at': last, 'run_type': 'scheduled'}

    health = sched._scheduled_health(_sched_cfg(), next_run_iso=None, embedded_skipped=False)
    assert health['stale'] is False


def test_long_vacation_gap_is_stale_with_catchup_hint(scheduler):
    sched, db = scheduler
    last = (datetime.now() - timedelta(days=10)).isoformat()
    db.get_last_pipeline_run.return_value = {'completed_at': last, 'run_type': 'scheduled'}

    health = sched._scheduled_health(_sched_cfg(), next_run_iso=None, embedded_skipped=False)
    assert health['stale'] is True
    assert 'startup catch-up' in health['message'].lower()


def test_running_pipeline_not_stale(scheduler):
    sched, db = scheduler
    last = (datetime.now() - timedelta(days=10)).isoformat()
    db.get_last_pipeline_run.return_value = {'completed_at': last, 'run_type': 'scheduled'}

    with _run_lock:
        _current_run.clear()
        _current_run.update({'status': 'running', 'step': 'fetch'})

    try:
        health = sched._scheduled_health(_sched_cfg(), next_run_iso=None, embedded_skipped=False)
        assert health['stale'] is False
        assert health['reason'] == 'pipeline_running'
    finally:
        with _run_lock:
            _current_run.clear()
