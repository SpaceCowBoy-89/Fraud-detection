"""Tests for MCP / PS7 source reconciliation."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from database import Database
from source_reconciliation import (
    McpHttpClient,
    NullSourceClient,
    SourceQueryClient,
    aggregate_day_status,
    build_source_client,
    compute_match_status,
    merge_reconciliation_into_coverage,
    reconcile_affiliates_for_day,
    reconcile_day_range,
    reconciliation_source_configured,
    _extract_mcp_tool_json,
    _parse_affiliate_daily_histogram,
    _parse_daily_histogram,
    _parse_mcp_sse_payload,
)


class MockSourceClient(SourceQueryClient):
    def __init__(self, daily=None, affiliates=None, affiliate_daily=None):
        self.daily = daily or {}
        self.affiliates = affiliates or {}
        self.affiliate_daily = affiliate_daily or {}

    def query_daily_counts(self, start_date, end_date):
        return {
            d: self.daily[d]
            for d in self.daily
            if start_date <= d <= end_date
        }

    def query_affiliate_counts(self, day):
        return self.affiliates.get(day, {})

    def query_affiliate_daily_counts(self, start_date, end_date):
        if self.affiliate_daily:
            return {
                d: self.affiliate_daily[d]
                for d in self.affiliate_daily
                if start_date <= d <= end_date
            }
        return super().query_affiliate_daily_counts(start_date, end_date)


def test_compute_match_status_complete_within_tolerance():
    pct, status = compute_match_status(17279, 17270, threshold_pct=99.5)
    assert status == 'complete'
    assert pct >= 99.5


def test_compute_match_status_partial():
    pct, status = compute_match_status(17000, 9500, threshold_pct=99.5)
    assert status == 'partial'
    assert pct < 99.5


def test_compute_match_status_missing():
    pct, status = compute_match_status(17000, 0, threshold_pct=99.5)
    assert status == 'missing'
    assert pct == 0.0


def test_aggregate_day_status():
    assert aggregate_day_status('complete', 'complete', 'complete') == 'complete'
    assert aggregate_day_status('complete', 'partial', 'complete') == 'partial'
    assert aggregate_day_status('source_unavailable', 'complete', 'complete') == 'source_unavailable'


def test_reconcile_day_range_persists_and_complete(tmp_path):
    dbp = str(tmp_path / 'recon.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        for i in range(100):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'f{i}', f'u{i}@x.com', '2026-07-03 12:00:00'),
            )
        for i in range(20):
            conn.execute(
                """INSERT INTO paid (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'p{i}', f'p{i}@x.com', '2026-07-03 12:00:00'),
            )
        conn.commit()

    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        'scheduler': {
            'mcp_reconciliation': {
                'enabled': True,
                'match_threshold_pct': 99.5,
                'source': 'mcp_ps7_ht_signups',
            },
        },
    }.get(k, default)

    client = MockSourceClient(daily={
        '2026-07-03': {'free': 100, 'paid': 20, 'total': 120},
    })
    summary = reconcile_day_range(db, config, client, '2026-07-03', '2026-07-03')
    assert summary['enabled'] is True
    assert summary['days'][0]['reconciliation_status'] == 'complete'

    stored = db.get_reconciliation_results('2026-07-03', '2026-07-03')
    assert stored['2026-07-03']['reconciliation_status'] == 'complete'
    assert stored['2026-07-03']['source_expected_total'] == 120


def test_reconcile_day_range_source_unavailable(tmp_path):
    dbp = str(tmp_path / 'recon2.db')
    db = Database(dbp)
    db.setup_database()

    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        'scheduler': {'mcp_reconciliation': {'enabled': True}},
    }.get(k, default)

    summary = reconcile_day_range(
        db, config, NullSourceClient(), '2026-07-03', '2026-07-03',
    )
    assert summary['days'][0]['reconciliation_status'] == 'source_unavailable'


def test_merge_reconciliation_marks_refetch():
    coverage = {
        'daily': [
            {
                'day': '2026-07-06',
                'fetched_total': 9585,
                'pipeline_stage': 'partial_analysis',
                'pending_analysis': 100,
                'source_analyzed': 200,
            },
        ],
        'refetch_days': [],
        'partial_days': [],
        'missing_days': [],
    }
    recon = {
        '2026-07-06': {
            'source_expected_total': 17609,
            'source_expected_free': 15019,
            'source_expected_paid': 2590,
            'local_match_pct': 54.4,
            'reconciliation_status': 'partial',
            'reconciliation_checked_at': '2026-07-09 10:00:00',
        },
    }
    merged = merge_reconciliation_into_coverage(coverage, recon, threshold_pct=99.5)
    assert merged['mcp_partial_count'] == 1
    assert merged['daily'][0]['pipeline_stage'] == 'partial_source_match'
    assert '2026-07-06' in merged['refetch_day_list']


def test_reconcile_affiliates_for_day(tmp_path):
    dbp = str(tmp_path / 'recon3.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        for i in range(5):
            conn.execute(
                """INSERT INTO free (duid, email, webmaster_code, trans_datetime, analyzed)
                   VALUES (?, ?, ?, ?, 0)""",
                (f'f{i}', f'u{i}@x.com', 'affa', '2026-07-06 12:00:00'),
            )
        conn.commit()

    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        'scheduler': {'mcp_reconciliation': {'match_threshold_pct': 99.5}},
    }.get(k, default)

    client = MockSourceClient(affiliates={
        '2026-07-06': {
            'affa': {'free': 50, 'paid': 10, 'total': 60},
            'affb': {'free': 100, 'paid': 0, 'total': 100},
        },
    })
    result = reconcile_affiliates_for_day(db, config, client, '2026-07-06')
    assert result['source_unavailable'] is False
    by_aff = {a['affiliate']: a for a in result['affiliates']}
    assert by_aff['affa']['status'] == 'partial'
    assert by_aff['affa']['missing_estimate'] == 55
    assert by_aff['affb']['status'] == 'missing'


def test_parse_mcp_sse_payload():
    raw = 'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\r\n\r\n'
    msg = _parse_mcp_sse_payload(raw)
    assert msg['result']['ok'] is True


def test_extract_mcp_tool_json_from_content():
    es_body = {'aggregations': {'by_day': {'buckets': []}}}
    result = {
        'content': [{'type': 'text', 'text': json.dumps(es_body)}],
        'isError': False,
    }
    assert _extract_mcp_tool_json(result) == es_body


def test_parse_daily_histogram():
    data = {
        'aggregations': {
            'by_day': {
                'buckets': [{
                    'key_as_string': '2026-07-03',
                    'by_type': {
                        'buckets': [
                            {'key': 'free', 'doc_count': 100},
                            {'key': 'paid', 'doc_count': 20},
                        ],
                    },
                }],
            },
        },
    }
    out = _parse_daily_histogram(data)
    assert out['2026-07-03'] == {'free': 100, 'paid': 20, 'total': 120}


def test_build_source_client_prefers_elasticsearch():
    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        'scheduler': {
            'mcp_reconciliation': {
                'elasticsearch_url': 'https://es.example.com',
                'mcp_url': 'http://mcp.example/mcp',
                'mcp_authorization': 'Bearer tok',
            },
        },
    }.get(k, default)
    from source_reconciliation import ElasticsearchHTTPClient
    client = build_source_client(config)
    assert isinstance(client, ElasticsearchHTTPClient)


def test_build_source_client_uses_mcp_when_no_es(monkeypatch):
    monkeypatch.setenv('CAMSODA_MCP_AUTH', 'mcp_test_token')
    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        'scheduler': {
            'mcp_reconciliation': {
                'elasticsearch_url': '',
                'mcp_url': 'http://mcp.example/mcp',
            },
        },
    }.get(k, default)
    client = build_source_client(config)
    assert isinstance(client, McpHttpClient)
    assert client.authorization == 'Bearer mcp_test_token'


def test_reconciliation_source_configured_mcp_env(monkeypatch):
    monkeypatch.delenv('CAMSODA_MCP_AUTH', raising=False)
    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {
        'scheduler': {
            'mcp_reconciliation': {
                'mcp_url': 'http://mcp.example/mcp',
            },
        },
    }.get(k, default)
    assert reconciliation_source_configured(config) is False
    monkeypatch.setenv('CAMSODA_MCP_AUTH', 'secret')
    assert reconciliation_source_configured(config) is True


def test_mcp_client_query_daily_counts():
    es_response = {
        'aggregations': {
            'by_day': {
                'buckets': [{
                    'key_as_string': '2026-07-03',
                    'by_type': {
                        'buckets': [
                            {'key': 'free', 'doc_count': 14463},
                            {'key': 'paid', 'doc_count': 2816},
                        ],
                    },
                }],
            },
        },
    }
    client = McpHttpClient(
        'http://mcp.example/mcp',
        'Bearer test',
    )

    def fake_call_tool(name, arguments):
        assert name == 'search'
        assert arguments['index'] == 'ps7-ht-signups-2026'
        assert arguments['size'] == 0
        return es_response

    with patch.object(client, '_call_tool', side_effect=fake_call_tool):
        out = client.query_daily_counts('2026-07-03', '2026-07-03')
    assert out['2026-07-03']['total'] == 17279


def test_parse_affiliate_daily_histogram():
    data = {
        'aggregations': {
            'by_day': {
                'buckets': [{
                    'key_as_string': '2026-07-09',
                    'by_affiliate': {
                        'buckets': [{
                            'key': 'FlashProfit',
                            'by_type': {
                                'buckets': [
                                    {'key': 'free', 'doc_count': 100},
                                    {'key': 'paid', 'doc_count': 20},
                                ],
                            },
                        }],
                    },
                }],
            },
        },
    }
    out = _parse_affiliate_daily_histogram(data)
    assert out['2026-07-09']['flashprofit']['total'] == 120
    assert out['2026-07-09']['flashprofit']['free'] == 100
