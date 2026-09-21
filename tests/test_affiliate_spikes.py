"""Tests for hybrid affiliate spike detection."""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from database import Database
from affiliate_spikes import detect_affiliate_spikes, paginate_spikes


def _seed_steady_then_spike(db_path: str, aff: str = 'flashprofit'):
    """14 steady days then a spike day (yesterday). Today left empty."""
    today = date.today()
    with sqlite3.connect(db_path) as conn:
        # Baseline: 10 free/day for 20 days ending 2 days ago
        for offset in range(20, 1, -1):
            day = today - timedelta(days=offset)
            for i in range(10):
                duid = f'{aff}-{offset}-{i}'
                conn.execute(
                    """INSERT INTO free (duid, email, trans_datetime, webmaster_code, analyzed)
                       VALUES (?, ?, ?, ?, 0)""",
                    (duid, f'{duid}@ex.com', f'{day.isoformat()} 12:00:00', aff),
                )
        # Spike yesterday: 80 accounts
        spike_day = today - timedelta(days=1)
        for i in range(80):
            duid = f'{aff}-spike-{i}'
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, webmaster_code, analyzed)
                   VALUES (?, ?, ?, ?, 0)""",
                (duid, f'{duid}@ex.com', f'{spike_day.isoformat()} 12:00:00', aff),
            )
        conn.commit()
    return spike_day.isoformat()


def test_detect_local_affiliate_spike(tmp_path):
    dbp = str(tmp_path / 'aff_spikes.db')
    db = Database(dbp)
    db.setup_database()
    spike_day = _seed_steady_then_spike(dbp)

    cfg = {
        'scheduler': {
            'volume_anomalies': {
                'prefer_source_counts': False,
                'exclude_today': True,
                'match_threshold_pct': 99.5,
            },
        },
    }
    result = detect_affiliate_spikes(db, cfg, lookback_days=30, min_count=5)
    assert result['hybrid']['counts_source'] == 'local'
    assert result['hybrid']['date_field'] == 'trans_datetime'
    hits = [s for s in result['spikes'] if s['webmaster_code'] == 'flashprofit']
    assert hits, 'expected spike for flashprofit'
    assert hits[0]['spike_date'] == spike_day
    assert hits[0]['spike_level'] in ('spike', 'severe')
    assert hits[0]['count'] == 80


def test_exclude_today_from_affiliate_spikes(tmp_path):
    dbp = str(tmp_path / 'aff_today.db')
    db = Database(dbp)
    db.setup_database()
    today = date.today()
    with sqlite3.connect(dbp) as conn:
        for offset in range(20, 0, -1):
            day = today - timedelta(days=offset)
            n = 10 if offset > 0 else 10
            for i in range(n):
                duid = f't-{offset}-{i}'
                conn.execute(
                    """INSERT INTO free (duid, email, trans_datetime, webmaster_code, analyzed)
                       VALUES (?, ?, ?, ?, 0)""",
                    (duid, f'{duid}@ex.com', f'{day.isoformat()} 10:00:00', 'todayaff'),
                )
        # Huge incomplete today
        for i in range(200):
            duid = f'today-{i}'
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, webmaster_code, analyzed)
                   VALUES (?, ?, ?, ?, 0)""",
                (duid, f'{duid}@ex.com', f'{today.isoformat()} 10:00:00', 'todayaff'),
            )
        conn.commit()

    cfg = {
        'scheduler': {
            'volume_anomalies': {
                'prefer_source_counts': False,
                'exclude_today': True,
            },
        },
    }
    result = detect_affiliate_spikes(db, cfg, lookback_days=30, min_count=5)
    assert not any(s['spike_date'] == today.isoformat() for s in result['spikes'])
    assert any(
        s['spike_date'] == today.isoformat() and s.get('excluded_reason') == 'day_in_progress'
        for s in result['excluded_spikes']
    )


def test_mcp_scoring_used_when_source_available(tmp_path):
    dbp = str(tmp_path / 'aff_mcp.db')
    db = Database(dbp)
    db.setup_database()
    today = date.today()
    spike_day = (today - timedelta(days=1)).isoformat()

    # Local only has partial counts; MCP has the real spike
    with sqlite3.connect(dbp) as conn:
        for offset in range(20, 1, -1):
            day = today - timedelta(days=offset)
            for i in range(10):
                duid = f'm-{offset}-{i}'
                conn.execute(
                    """INSERT INTO free (duid, email, trans_datetime, webmaster_code, analyzed)
                       VALUES (?, ?, ?, ?, 0)""",
                    (duid, f'{duid}@ex.com', f'{day.isoformat()} 12:00:00', 'mcpaff'),
                )
        # Local only fetched 5 of 80 on spike day
        for i in range(5):
            duid = f'm-spike-{i}'
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, webmaster_code, analyzed)
                   VALUES (?, ?, ?, ?, 0)""",
                (duid, f'{duid}@ex.com', f'{spike_day} 12:00:00', 'mcpaff'),
            )
        conn.commit()

    affiliate_daily = {}
    for offset in range(20, 1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        affiliate_daily[day] = {'mcpaff': {'free': 10, 'paid': 0, 'total': 10}}
    affiliate_daily[spike_day] = {'mcpaff': {'free': 80, 'paid': 0, 'total': 80}}

    cfg = {
        'scheduler': {
            'volume_anomalies': {
                'prefer_source_counts': True,
                'exclude_today': True,
                'match_threshold_pct': 99.5,
            },
            'mcp_reconciliation': {
                'enabled': True,
                'mcp_url': 'http://example/mcp',
                'mcp_authorization': 'Bearer x',
            },
        },
    }

    with patch('affiliate_spikes._fetch_source_affiliate_daily', return_value=affiliate_daily):
        result = detect_affiliate_spikes(db, cfg, lookback_days=30, min_count=5)

    assert result['hybrid']['counts_source'] == 'mcp'
    hits = [s for s in result['spikes'] if s['webmaster_code'] == 'mcpaff']
    assert hits
    assert hits[0]['count'] == 80
    assert hits[0]['local_count'] == 5
    assert hits[0]['source_used_for_scoring'] is True


def test_paginate_spikes():
    result = {
        'spikes': [{'webmaster_code': f'a{i}', 'z_score': i} for i in range(45)],
        'summary': {'total': 45},
    }
    page1 = paginate_spikes(result, page=1, per_page=20)
    assert len(page1['spikes']) == 20
    assert page1['pagination']['total_pages'] == 3
    page3 = paginate_spikes(result, page=3, per_page=20)
    assert len(page3['spikes']) == 5
