"""Tests for business volume anomaly detection (registrations + sales)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from volume_anomalies import (
    ANOMALY_LEVELS,
    analyze_volume_anomalies,
    apply_hybrid_metadata,
    classify_z,
    get_volume_anomaly_config,
)


def test_classify_z_surge_and_dip():
    assert classify_z(3.5) == 'surge_severe'
    assert classify_z(2.2) == 'surge'
    assert classify_z(1.6) == 'elevated_up'
    assert classify_z(0.5) == 'normal'
    assert classify_z(-1.6) == 'elevated_down'
    assert classify_z(-2.2) == 'dip'
    assert classify_z(-3.5) == 'dip_severe'
    assert classify_z(None) == 'normal'
    assert classify_z(float('nan')) == 'normal'


def test_analyze_detects_registration_surge():
    days = pd.date_range('2026-01-01', periods=30, freq='D')
    reg = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'registrations': [100] * 29 + [500],
    })
    sales = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'sales': [10] * 30,
    })
    result = analyze_volume_anomalies(reg, sales)
    assert len(result['daily']) == 30
    last = result['daily'][-1]
    assert last['registrations'] == 500
    assert last['registration_level'] in ANOMALY_LEVELS
    assert last['registration_z'] is not None
    assert last['registration_z'] >= 2.0
    assert any(a['date'] == last['date'] for a in result['anomalies'])


def test_analyze_detects_sales_dip():
    days = pd.date_range('2026-02-01', periods=30, freq='D')
    reg = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'registrations': [200] * 30,
    })
    sales = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'sales': [50] * 29 + [2],
    })
    result = analyze_volume_anomalies(reg, sales)
    last = result['daily'][-1]
    assert last['sales'] == 2
    assert last['sales_level'] in ('dip', 'dip_severe')
    assert last['sales_z'] is not None
    assert last['sales_z'] <= -2.0


def test_analyze_empty_data():
    result = analyze_volume_anomalies(pd.DataFrame(), pd.DataFrame())
    assert result['daily'] == []
    assert result['anomalies'] == []
    assert result['baseline'] == {}


def test_analyze_merges_registration_only_days():
    reg = pd.DataFrame({'day': ['2026-03-01', '2026-03-02'], 'registrations': [10, 20]})
    sales = pd.DataFrame({'day': ['2026-03-02'], 'sales': [3]})
    result = analyze_volume_anomalies(reg, sales)
    assert len(result['daily']) == 2
    by_date = {d['date']: d for d in result['daily']}
    assert by_date['2026-03-01']['registrations'] == 10
    assert by_date['2026-03-01']['sales'] == 0
    assert by_date['2026-03-02']['sales'] == 3


def test_conversion_rate_computed():
    days = pd.date_range('2026-04-01', periods=20, freq='D')
    reg = pd.DataFrame({'day': days.strftime('%Y-%m-%d'), 'registrations': [100] * 20})
    sales = pd.DataFrame({'day': days.strftime('%Y-%m-%d'), 'sales': [25] * 20})
    result = analyze_volume_anomalies(reg, sales)
    assert result['daily'][-1]['conversion_rate'] == 25.0


def test_get_volume_anomaly_config_merges_scheduler():
    cfg = {
        'scheduler': {
            'volume_anomalies': {'match_threshold_pct': 98.0},
            'mcp_reconciliation': {'match_threshold_pct': 99.5},
        }
    }
    out = get_volume_anomaly_config(cfg)
    assert out['match_threshold_pct'] == 98.0
    assert out['prefer_source_counts'] is True
    assert out['exclude_today'] is True


def test_apply_hybrid_metadata_excludes_day_in_progress():
    """Open calendar day must not surface as dip/surge against a full-day baseline."""
    from datetime import date

    today = date.today().isoformat()
    days = pd.date_range(end=today, periods=30, freq='D')
    reg = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'registrations': [100] * 29 + [40],
    })
    sales = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'sales': [10] * 29 + [2],
    })
    result = analyze_volume_anomalies(reg, sales)
    assert any(a['date'] == today for a in result['anomalies'])

    day_meta = {
        today: {
            'local_registrations': 0,
            'local_sales': 0,
            'source_registrations': 40,
            'source_sales': 2,
            'local_match_pct': 0.0,
            'local_data_complete': False,
            'source_used_for_scoring': True,
            'partial_fetch': True,
            'day_in_progress': True,
        }
    }
    enriched = apply_hybrid_metadata(result, day_meta)
    assert not any(a['date'] == today for a in enriched['anomalies'])
    excluded = next(a for a in enriched['excluded_anomalies'] if a['date'] == today)
    assert excluded['excluded_reason'] == 'day_in_progress'
    daily_today = next(d for d in enriched['daily'] if d['date'] == today)
    assert daily_today['registration_level'] == 'in_progress'
    assert daily_today['sales_level'] == 'in_progress'


def test_apply_hybrid_metadata_excludes_partial_local_only_dip():
    """Partial local dip without MCP scoring should not appear in anomalies."""
    days = pd.date_range('2026-07-01', periods=30, freq='D')
    # Local-only low counts on last day (would be dip)
    reg = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'registrations': [100] * 29 + [20],
    })
    sales = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'sales': [10] * 30,
    })
    result = analyze_volume_anomalies(reg, sales)
    last_day = days.strftime('%Y-%m-%d')[-1]
    day_meta = {
        last_day: {
            'local_registrations': 20,
            'local_sales': 10,
            'source_registrations': 100,
            'source_sales': 10,
            'local_match_pct': 20.0,
            'local_data_complete': False,
            'source_used_for_scoring': False,
            'partial_fetch': True,
            'day_in_progress': False,
            'reconciliation_status': 'partial',
        }
    }
    enriched = apply_hybrid_metadata(result, day_meta)
    assert not any(a['date'] == last_day for a in enriched['anomalies'])
    assert any(a['date'] == last_day for a in enriched['excluded_anomalies'])


def test_apply_hybrid_metadata_keeps_anomaly_when_mcp_scored():
    """Real anomaly with MCP scoring stays even if local fetch was partial."""
    days = pd.date_range('2026-07-01', periods=30, freq='D')
    reg = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'registrations': [100] * 29 + [500],
    })
    sales = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'sales': [10] * 30,
    })
    result = analyze_volume_anomalies(reg, sales)
    last_day = days.strftime('%Y-%m-%d')[-1]
    day_meta = {
        last_day: {
            'local_registrations': 200,
            'local_sales': 10,
            'source_registrations': 500,
            'source_sales': 10,
            'local_match_pct': 40.0,
            'local_data_complete': False,
            'source_used_for_scoring': True,
            'partial_fetch': True,
            'day_in_progress': False,
            'reconciliation_status': 'partial',
        }
    }
    enriched = apply_hybrid_metadata(result, day_meta)
    assert any(a['date'] == last_day for a in enriched['anomalies'])
    assert enriched['anomalies'][0]['partial_fetch'] is True


def test_mcp_scoring_prevents_false_dip_on_partial_day():
    """When scoring uses MCP full counts, partial local should not dip."""
    days = pd.date_range('2026-07-01', periods=30, freq='D')
    # Score series uses MCP (~100/day); local was only 32% on last day
    reg = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'registrations': [100] * 30,
    })
    sales = pd.DataFrame({
        'day': days.strftime('%Y-%m-%d'),
        'sales': [10] * 30,
    })
    result = analyze_volume_anomalies(reg, sales)
    last_day = days.strftime('%Y-%m-%d')[-1]
    day_meta = {
        last_day: {
            'local_registrations': 32,
            'local_sales': 8,
            'source_registrations': 100,
            'source_sales': 10,
            'local_match_pct': 32.0,
            'local_data_complete': False,
            'source_used_for_scoring': True,
            'partial_fetch': True,
            'day_in_progress': False,
        }
    }
    enriched = apply_hybrid_metadata(result, day_meta)
    last = next(d for d in enriched['daily'] if d['date'] == last_day)
    assert last['registration_level'] == 'normal'
    assert not any(a['date'] == last_day for a in enriched['anomalies'])
