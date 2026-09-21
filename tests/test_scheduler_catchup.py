"""Catch-up optimizations: day chunking and skip enrichment."""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scheduler import FraudPipelineScheduler, iter_catchup_day_range


@pytest.fixture
def scheduler():
    db = MagicMock()
    cfg = {
        'scheduler': {
            'catchup_chunk_days': True,
            'catchup_skip_enrichment': True,
        },
        'min_duid_threshold': 0,
        'risk_thresholds': {'high': 50, 'medium': 25},
    }
    config = MagicMock()
    config.config = cfg
    config.get.side_effect = lambda k, default=None: cfg.get(k, default)
    config.get_house_affiliates.return_value = []
    config.get_risk_threshold.side_effect = lambda k: cfg['risk_thresholds'].get(k)
    config.get_admin_api_credentials.return_value = ('user', 'pass')
    sched = FraudPipelineScheduler(db=db, config=config, api_client=MagicMock())
    sched._available = True
    return sched


def test_iter_catchup_day_range_inclusive():
    days = list(iter_catchup_day_range(5, end_date=date(2026, 6, 24)))
    assert days == [
        '2026-06-19',
        '2026-06-20',
        '2026-06-21',
        '2026-06-22',
        '2026-06-23',
        '2026-06-24',
    ]


def test_iter_catchup_day_range_single_day():
    assert list(iter_catchup_day_range(1, end_date=date(2026, 6, 24))) == ['2026-06-23', '2026-06-24']


def test_trigger_catchup_chunks_when_multi_day(scheduler):
    with patch.object(scheduler, '_run_catchup_chunked') as chunked:
        scheduler.trigger_catchup(days_back=5)
        import time
        time.sleep(0.05)
    chunked.assert_called_once_with(total_days_back=5)


def test_trigger_catchup_single_day_no_chunk(scheduler):
    with patch.object(scheduler, '_run_pipeline') as run:
        scheduler.trigger_catchup(days_back=1)
        import time
        time.sleep(0.05)
    run.assert_called_once_with(days_back=1, trigger='catchup')


def test_run_catchup_chunked_calls_pipeline_per_day(scheduler):
    with patch('scheduler.iter_catchup_day_range', return_value=['2026-06-19', '2026-06-20']):
        with patch.object(scheduler, '_run_pipeline') as run:
            scheduler._run_catchup_chunked(2)
    assert run.call_count == 2
    for call in run.call_args_list:
        assert call.kwargs['trigger'] == 'catchup'
        assert call.kwargs['start_date'] == call.kwargs['end_date']
        assert 'catchup_chunk' in call.kwargs


def test_chunking_disabled_uses_single_run(scheduler):
    scheduler.config.config['scheduler']['catchup_chunk_days'] = False
    with patch.object(scheduler, '_run_pipeline') as run:
        scheduler.trigger_catchup(days_back=5)
        import time
        time.sleep(0.05)
    run.assert_called_once_with(days_back=5, trigger='catchup')
