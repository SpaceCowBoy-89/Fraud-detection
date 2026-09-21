"""
MCP / PS7 source reconciliation — compare Elasticsearch signup counts to local DB.

The operational pipeline still fetches via HugeTraffic API. This module validates
completeness against PS7 HugeTraffic signups (ps7-ht-signups-*).
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SOURCE_PS7_HT_SIGNUPS = 'mcp_ps7_ht_signups'


def _parse_day(s: str):
    return datetime.strptime(s, '%Y-%m-%d').date()


def _iter_days(start_date: str, end_date: str):
    start = _parse_day(start_date)
    end = _parse_day(end_date)
    cur = start
    while cur <= end:
        yield cur.strftime('%Y-%m-%d')
        cur += timedelta(days=1)


def compute_match_status(
    expected: int,
    local: int,
    *,
    threshold_pct: float = 99.5,
) -> tuple[float, str]:
    """Return (match_pct, status) for one count pair."""
    expected = int(expected or 0)
    local = int(local or 0)
    if expected < 1 and local < 1:
        return 100.0, 'complete'
    if expected < 1 and local > 0:
        return 0.0, 'unknown'
    if local < 1:
        return 0.0, 'missing'
    match_pct = round(100.0 * local / expected, 2)
    if match_pct >= float(threshold_pct):
        return match_pct, 'complete'
    return match_pct, 'partial'


def aggregate_day_status(
    free_status: str,
    paid_status: str,
    total_status: str,
) -> str:
    """Overall day reconciliation status."""
    statuses = [free_status, paid_status, total_status]
    if any(s == 'source_unavailable' for s in statuses):
        return 'source_unavailable'
    if any(s == 'missing' for s in statuses):
        return 'missing'
    if any(s == 'partial' for s in statuses):
        return 'partial'
    if all(s == 'complete' for s in statuses):
        return 'complete'
    return 'unknown'


class SourceQueryClient(ABC):
    """Mockable interface for PS7 signup count queries."""

    @abstractmethod
    def query_daily_counts(self, start_date: str, end_date: str) -> Dict[str, Dict[str, int]]:
        """
        Return {day: {free: N, paid: N, total: N}} from source.
        Raise on hard failures; return {} if unavailable.
        """

    @abstractmethod
    def query_affiliate_counts(self, day: str) -> Dict[str, Dict[str, int]]:
        """Return {affiliate_lower: {free, paid, total}} for one day."""

    def query_affiliate_daily_counts(
        self, start_date: str, end_date: str,
    ) -> Dict[str, Dict[str, Dict[str, int]]]:
        """
        Return {day: {affiliate_lower: {free, paid, total}}} for a date range.

        Default implementation walks day-by-day via query_affiliate_counts.
        HTTP/MCP clients override with a single nested aggregation.
        """
        out: Dict[str, Dict[str, Dict[str, int]]] = {}
        for day in _iter_days(start_date, end_date):
            affs = self.query_affiliate_counts(day)
            if affs:
                out[day] = affs
        return out


class NullSourceClient(SourceQueryClient):
    """Used when ES/MCP is not configured."""

    def query_daily_counts(self, start_date: str, end_date: str) -> Dict[str, Dict[str, int]]:
        return {}

    def query_affiliate_counts(self, day: str) -> Dict[str, Dict[str, int]]:
        return {}

    def query_affiliate_daily_counts(
        self, start_date: str, end_date: str,
    ) -> Dict[str, Dict[str, Dict[str, int]]]:
        return {}


def _indices_for_range(
    index_pattern: str,
    start_date: str,
    end_date: str,
) -> str:
    start = _parse_day(start_date)
    end = _parse_day(end_date)
    years = sorted({start.year, end.year})
    return ','.join(index_pattern.format(year=y) for y in years)


def _parse_daily_histogram(data: dict) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    buckets = (
        data.get('aggregations', {})
        .get('by_day', {})
        .get('buckets', [])
    )
    for bucket in buckets:
        day = bucket.get('key_as_string') or bucket.get('key')
        if not day:
            continue
        day = str(day)[:10]
        free_c = paid_c = 0
        for tb in bucket.get('by_type', {}).get('buckets', []):
            key = str(tb.get('key', '')).lower()
            cnt = int(tb.get('doc_count') or 0)
            if key == 'free':
                free_c = cnt
            elif key == 'paid':
                paid_c = cnt
        out[day] = {
            'free': free_c,
            'paid': paid_c,
            'total': free_c + paid_c,
        }
    return out


def _parse_affiliate_terms(data: dict) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    buckets = (
        data.get('aggregations', {})
        .get('by_affiliate', {})
        .get('buckets', [])
    )
    for bucket in buckets:
        aff = str(bucket.get('key') or '').strip().lower()
        if not aff:
            continue
        free_c = paid_c = 0
        for tb in bucket.get('by_type', {}).get('buckets', []):
            key = str(tb.get('key', '')).lower()
            cnt = int(tb.get('doc_count') or 0)
            if key == 'free':
                free_c = cnt
            elif key == 'paid':
                paid_c = cnt
        out[aff] = {
            'free': free_c,
            'paid': paid_c,
            'total': free_c + paid_c,
        }
    return out


def _parse_affiliate_daily_histogram(data: dict) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Parse nested by_day → by_affiliate → by_type aggregations."""
    out: Dict[str, Dict[str, Dict[str, int]]] = {}
    day_buckets = (
        data.get('aggregations', {})
        .get('by_day', {})
        .get('buckets', [])
    )
    for day_bucket in day_buckets:
        day = day_bucket.get('key_as_string') or day_bucket.get('key')
        if not day:
            continue
        day = str(day)[:10]
        aff_out: Dict[str, Dict[str, int]] = {}
        for aff_bucket in day_bucket.get('by_affiliate', {}).get('buckets', []):
            aff = str(aff_bucket.get('key') or '').strip().lower()
            if not aff:
                continue
            free_c = paid_c = 0
            for tb in aff_bucket.get('by_type', {}).get('buckets', []):
                key = str(tb.get('key', '')).lower()
                cnt = int(tb.get('doc_count') or 0)
                if key == 'free':
                    free_c = cnt
                elif key == 'paid':
                    paid_c = cnt
            aff_out[aff] = {
                'free': free_c,
                'paid': paid_c,
                'total': free_c + paid_c,
            }
        if aff_out:
            out[day] = aff_out
    return out


def _parse_mcp_sse_payload(raw: str) -> dict:
    """Extract JSON-RPC message from MCP SSE (event: message / data: {...})."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith('data:'):
            payload = line[5:].strip()
            if payload:
                return json.loads(payload)
    stripped = raw.strip()
    if stripped.startswith('{'):
        return json.loads(stripped)
    raise RuntimeError(f'MCP response missing SSE data payload: {raw[:300]!r}')


def _extract_mcp_tool_json(result: dict) -> dict:
    """Parse Elasticsearch JSON returned by MCP search tool."""
    if result.get('isError'):
        parts = []
        for block in result.get('content') or []:
            if isinstance(block, dict) and block.get('text'):
                parts.append(str(block['text']))
        raise RuntimeError('MCP tool error: ' + (' '.join(parts) or 'unknown'))

    structured = result.get('structuredContent') or {}
    if isinstance(structured.get('result'), str):
        return json.loads(structured['result'])
    if isinstance(structured.get('result'), dict):
        return structured['result']

    for block in result.get('content') or []:
        if isinstance(block, dict) and block.get('type') == 'text' and block.get('text'):
            return json.loads(block['text'])
    raise RuntimeError('MCP tool result missing Elasticsearch JSON')


class ElasticsearchHTTPClient(SourceQueryClient):
    """Query PS7 signups index via Elasticsearch HTTP API."""

    def __init__(self, base_url: str, api_key: str = '', index_pattern: str = 'ps7-ht-signups-{year}'):
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = (api_key or '').strip()
        self.index_pattern = index_pattern or 'ps7-ht-signups-{year}'

    def _headers(self) -> dict:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'ApiKey {self.api_key}'
        return headers

    def _search(self, index: str, body: dict) -> dict:
        import urllib.error
        import urllib.request

        url = f'{self.base_url}/{index}/_search'
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode('utf-8'),
            headers=self._headers(),
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode('utf-8', errors='replace')[:500]
            raise RuntimeError(f'Elasticsearch HTTP {exc.code}: {err_body}') from exc
        except Exception as exc:
            raise RuntimeError(f'Elasticsearch request failed: {exc}') from exc

    def query_daily_counts(self, start_date: str, end_date: str) -> Dict[str, Dict[str, int]]:
        if not self.base_url:
            return {}
        index = _indices_for_range(self.index_pattern, start_date, end_date)
        body = {
            'size': 0,
            'query': {
                'range': {
                    'trans_date': {'gte': start_date, 'lte': end_date},
                },
            },
            'aggs': {
                'by_day': {
                    'date_histogram': {
                        'field': 'trans_date',
                        'calendar_interval': 'day',
                        'format': 'yyyy-MM-dd',
                    },
                    'aggs': {
                        'by_type': {
                            'terms': {'field': 'record_type', 'size': 5},
                        },
                    },
                },
            },
        }
        return _parse_daily_histogram(self._search(index, body))

    def query_affiliate_counts(self, day: str) -> Dict[str, Dict[str, int]]:
        if not self.base_url:
            return {}
        index = _indices_for_range(self.index_pattern, day, day)
        body = {
            'size': 0,
            'query': {
                'bool': {
                    'filter': [
                        {'term': {'trans_date': day}},
                    ],
                },
            },
            'aggs': {
                'by_affiliate': {
                    'terms': {'field': 'webmaster_code', 'size': 500},
                    'aggs': {
                        'by_type': {
                            'terms': {'field': 'record_type', 'size': 5},
                        },
                    },
                },
            },
        }
        return _parse_affiliate_terms(self._search(index, body))

    def query_affiliate_daily_counts(
        self, start_date: str, end_date: str,
    ) -> Dict[str, Dict[str, Dict[str, int]]]:
        if not self.base_url:
            return {}
        index = _indices_for_range(self.index_pattern, start_date, end_date)
        body = {
            'size': 0,
            'query': {
                'range': {
                    'trans_date': {'gte': start_date, 'lte': end_date},
                },
            },
            'aggs': {
                'by_day': {
                    'date_histogram': {
                        'field': 'trans_date',
                        'calendar_interval': 'day',
                        'format': 'yyyy-MM-dd',
                    },
                    'aggs': {
                        'by_affiliate': {
                            'terms': {'field': 'webmaster_code', 'size': 1000},
                            'aggs': {
                                'by_type': {
                                    'terms': {'field': 'record_type', 'size': 5},
                                },
                            },
                        },
                    },
                },
            },
        }
        return _parse_affiliate_daily_histogram(self._search(index, body))


class McpHttpClient(SourceQueryClient):
    """Query PS7 signups via MCP HTTP (tools/call search) — no raw ES credentials."""

    def __init__(
        self,
        mcp_url: str,
        authorization: str,
        index_pattern: str = 'ps7-ht-signups-{year}',
    ):
        self.mcp_url = (mcp_url or '').rstrip('/')
        auth = (authorization or '').strip()
        if auth and not auth.lower().startswith('bearer '):
            auth = f'Bearer {auth}'
        self.authorization = auth
        self.index_pattern = index_pattern or 'ps7-ht-signups-{year}'
        self._session_id: Optional[str] = None
        self._rpc_id = 0

    def _next_rpc_id(self) -> str:
        self._rpc_id += 1
        return str(self._rpc_id)

    def _post(self, payload: dict, session_id: Optional[str] = None) -> tuple[Optional[str], str]:
        import urllib.error
        import urllib.request

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'Authorization': self.authorization,
        }
        if session_id:
            headers['Mcp-Session-Id'] = session_id
        req = urllib.request.Request(
            self.mcp_url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                sid = resp.headers.get('Mcp-Session-Id') or session_id
                return sid, resp.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode('utf-8', errors='replace')[:500]
            raise RuntimeError(f'MCP HTTP {exc.code}: {err_body}') from exc
        except Exception as exc:
            raise RuntimeError(f'MCP request failed: {exc}') from exc

    def _reset_session(self) -> None:
        self._session_id = None

    def _ensure_session(self) -> None:
        if self._session_id:
            return
        sid, raw = self._post({
            'jsonrpc': '2.0',
            'id': self._next_rpc_id(),
            'method': 'initialize',
            'params': {
                'protocolVersion': '2024-11-05',
                'capabilities': {},
                'clientInfo': {'name': 'fraud-detection', 'version': '1.0'},
            },
        })
        msg = _parse_mcp_sse_payload(raw)
        if msg.get('error'):
            raise RuntimeError(f'MCP initialize failed: {msg["error"]}')
        if not sid:
            raise RuntimeError('MCP initialize did not return Mcp-Session-Id')
        self._session_id = sid
        self._post({
            'jsonrpc': '2.0',
            'method': 'notifications/initialized',
            'params': {},
        }, session_id=self._session_id)

    def _call_tool(self, name: str, arguments: dict) -> dict:
        if not self.mcp_url:
            return {}
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                self._ensure_session()
                _, raw = self._post({
                    'jsonrpc': '2.0',
                    'id': self._next_rpc_id(),
                    'method': 'tools/call',
                    'params': {'name': name, 'arguments': arguments},
                }, session_id=self._session_id)
                msg = _parse_mcp_sse_payload(raw)
                if msg.get('error'):
                    raise RuntimeError(f'MCP tools/call error: {msg["error"]}')
                return _extract_mcp_tool_json(msg.get('result') or {})
            except Exception as exc:
                last_exc = exc
                self._reset_session()
                if attempt == 0:
                    logger.debug('MCP call retry after: %s', exc)
                    continue
                raise
        raise RuntimeError(f'MCP call failed: {last_exc}')

    def _search_index(
        self,
        index: str,
        *,
        query: dict,
        aggs: dict,
        size: int = 0,
    ) -> dict:
        return self._call_tool('search', {
            'index': index,
            'query': query,
            'aggs': aggs,
            'size': size,
        })

    def query_daily_counts(self, start_date: str, end_date: str) -> Dict[str, Dict[str, int]]:
        if not self.mcp_url:
            return {}
        index = _indices_for_range(self.index_pattern, start_date, end_date)
        data = self._search_index(
            index,
            query={'range': {'trans_date': {'gte': start_date, 'lte': end_date}}},
            aggs={
                'by_day': {
                    'date_histogram': {
                        'field': 'trans_date',
                        'calendar_interval': 'day',
                        'format': 'yyyy-MM-dd',
                    },
                    'aggs': {
                        'by_type': {
                            'terms': {'field': 'record_type', 'size': 5},
                        },
                    },
                },
            },
        )
        return _parse_daily_histogram(data)

    def query_affiliate_counts(self, day: str) -> Dict[str, Dict[str, int]]:
        if not self.mcp_url:
            return {}
        index = _indices_for_range(self.index_pattern, day, day)
        data = self._search_index(
            index,
            query={'bool': {'filter': [{'term': {'trans_date': day}}]}},
            aggs={
                'by_affiliate': {
                    'terms': {'field': 'webmaster_code', 'size': 500},
                    'aggs': {
                        'by_type': {
                            'terms': {'field': 'record_type', 'size': 5},
                        },
                    },
                },
            },
        )
        return _parse_affiliate_terms(data)

    def query_affiliate_daily_counts(
        self, start_date: str, end_date: str,
    ) -> Dict[str, Dict[str, Dict[str, int]]]:
        if not self.mcp_url:
            return {}
        index = _indices_for_range(self.index_pattern, start_date, end_date)
        data = self._search_index(
            index,
            query={'range': {'trans_date': {'gte': start_date, 'lte': end_date}}},
            aggs={
                'by_day': {
                    'date_histogram': {
                        'field': 'trans_date',
                        'calendar_interval': 'day',
                        'format': 'yyyy-MM-dd',
                    },
                    'aggs': {
                        'by_affiliate': {
                            'terms': {'field': 'webmaster_code', 'size': 1000},
                            'aggs': {
                                'by_type': {
                                    'terms': {'field': 'record_type', 'size': 5},
                                },
                            },
                        },
                    },
                },
            },
        )
        return _parse_affiliate_daily_histogram(data)


def get_mcp_reconciliation_config(config) -> dict:
    sched = config.get('scheduler', {}) or {}
    rc = sched.get('mcp_reconciliation') or {}
    return rc if isinstance(rc, dict) else {}


def reconciliation_source_configured(config) -> bool:
    """True when direct ES or MCP HTTP transport is configured."""
    rc = get_mcp_reconciliation_config(config)
    if str(rc.get('elasticsearch_url') or '').strip():
        return True
    mcp_url = str(rc.get('mcp_url') or os.environ.get('CAMSODA_MCP_URL', '')).strip()
    if not mcp_url:
        return False
    auth_env = str(rc.get('mcp_auth_env') or 'CAMSODA_MCP_AUTH').strip()
    auth = str(rc.get('mcp_authorization') or os.environ.get(auth_env, '') or '').strip()
    return bool(auth)


def build_source_client(config) -> SourceQueryClient:
    """Factory: ES HTTP if configured, else MCP HTTP, else null client."""
    rc = get_mcp_reconciliation_config(config)
    index_pattern = str(rc.get('index_pattern') or 'ps7-ht-signups-{year}')

    es_url = str(rc.get('elasticsearch_url') or '').strip()
    if es_url:
        return ElasticsearchHTTPClient(
            base_url=es_url,
            api_key=str(rc.get('elasticsearch_api_key') or ''),
            index_pattern=index_pattern,
        )

    mcp_url = str(rc.get('mcp_url') or os.environ.get('CAMSODA_MCP_URL', '')).strip()
    auth_env = str(rc.get('mcp_auth_env') or 'CAMSODA_MCP_AUTH').strip()
    auth = str(rc.get('mcp_authorization') or os.environ.get(auth_env, '') or '').strip()
    if mcp_url and auth:
        return McpHttpClient(
            mcp_url=mcp_url,
            authorization=auth,
            index_pattern=index_pattern,
        )

    return NullSourceClient()


def reconcile_day_range(
    db,
    config,
    client: Optional[SourceQueryClient],
    start_date: str,
    end_date: str,
) -> dict:
    """
    Compare source expected counts to local DB for each day in range.
    Persists rows and returns summary dict.
    """
    sched = config.get('scheduler', {}) or {}
    rc = get_mcp_reconciliation_config(config)
    if not rc.get('enabled', True):
        return {'enabled': False, 'days': []}

    source = str(rc.get('source') or SOURCE_PS7_HT_SIGNUPS)
    threshold = float(rc.get('match_threshold_pct', 99.5) or 99.5)
    client = client or NullSourceClient()

    local_daily = {
        row['day']: row
        for row in db.get_daily_pipeline_coverage(start_date, end_date)
    }

    try:
        if isinstance(client, NullSourceClient):
            raise RuntimeError('source client not configured')
        expected_by_day = client.query_daily_counts(start_date, end_date)
        source_ok = True
    except Exception as exc:
        logger.warning('Source reconciliation query failed: %s', exc)
        expected_by_day = {}
        source_ok = False

    results = []
    for day in _iter_days(start_date, end_date):
        local = local_daily.get(day, {})
        loc_free = int(local.get('free_count') or 0)
        loc_paid = int(local.get('paid_count') or 0)
        loc_total = int(local.get('fetched_total') or (loc_free + loc_paid))

        if not source_ok:
            for rtype, loc, exp_val in (
                ('free', loc_free, None),
                ('paid', loc_paid, None),
                ('total', loc_total, None),
            ):
                db.record_reconciliation_result(
                    day, source, rtype, exp_val, loc, None, 'source_unavailable',
                )
            results.append({
                'day': day,
                'reconciliation_status': 'source_unavailable',
                'source_expected_total': None,
                'local_total': loc_total,
                'local_match_pct': None,
            })
            continue

        exp = expected_by_day.get(day, {'free': 0, 'paid': 0, 'total': 0})
        exp_free = int(exp.get('free') or 0)
        exp_paid = int(exp.get('paid') or 0)
        exp_total = int(exp.get('total') or (exp_free + exp_paid))

        type_rows = []
        for rtype, exp_c, loc_c in (
            ('free', exp_free, loc_free),
            ('paid', exp_paid, loc_paid),
            ('total', exp_total, loc_total),
        ):
            match_pct, status = compute_match_status(exp_c, loc_c, threshold_pct=threshold)
            db.record_reconciliation_result(
                day, source, rtype, exp_c, loc_c, match_pct, status,
            )
            type_rows.append((rtype, status))

        overall = aggregate_day_status(
            type_rows[0][1], type_rows[1][1], type_rows[2][1],
        )
        match_total, _ = compute_match_status(exp_total, loc_total, threshold_pct=threshold)
        results.append({
            'day': day,
            'reconciliation_status': overall,
            'source_expected_free': exp_free,
            'source_expected_paid': exp_paid,
            'source_expected_total': exp_total,
            'local_free': loc_free,
            'local_paid': loc_paid,
            'local_total': loc_total,
            'local_match_pct': match_total,
        })

    return {
        'enabled': True,
        'start_date': start_date,
        'end_date': end_date,
        'source': source,
        'days': results,
    }


def reconcile_affiliates_for_day(
    db,
    config,
    client: Optional[SourceQueryClient],
    day: str,
    *,
    threshold_pct: float = None,
) -> dict:
    """Affiliate-level expected vs local for one day."""
    rc = get_mcp_reconciliation_config(config)
    threshold = float(
        threshold_pct if threshold_pct is not None
        else rc.get('match_threshold_pct', 99.5) or 99.5
    )
    client = client or NullSourceClient()

    local_rows = db.get_local_affiliate_counts_for_day(day)
    local_by = {r['affiliate']: r for r in local_rows}

    try:
        expected_by = client.query_affiliate_counts(day)
    except Exception as exc:
        logger.warning('Affiliate reconciliation failed for %s: %s', day, exc)
        return {
            'day': day,
            'source_unavailable': True,
            'affiliates': [],
            'error': str(exc),
        }

    if isinstance(client, NullSourceClient) or not expected_by:
        return {
            'day': day,
            'source_unavailable': True,
            'affiliates': [
                {
                    **loc,
                    'expected_free': None,
                    'expected_paid': None,
                    'expected_total': None,
                    'match_pct': None,
                    'missing_estimate': None,
                    'status': 'source_unavailable',
                }
                for loc in local_rows[:100]
            ],
        }

    all_affs = set(local_by) | set(expected_by)
    out = []
    for aff in all_affs:
        loc = local_by.get(aff, {'local_free': 0, 'local_paid': 0, 'local_total': 0})
        exp = expected_by.get(aff, {'free': 0, 'paid': 0, 'total': 0})
        exp_total = int(exp.get('total') or 0)
        loc_total = int(loc.get('local_total') or 0)
        match_pct, status = compute_match_status(exp_total, loc_total, threshold_pct=threshold)
        missing = max(0, exp_total - loc_total) if exp_total else 0
        if status == 'complete' and missing > 0:
            missing = 0
        out.append({
            'affiliate': aff,
            'expected_free': int(exp.get('free') or 0),
            'expected_paid': int(exp.get('paid') or 0),
            'expected_total': exp_total,
            'local_free': int(loc.get('local_free') or 0),
            'local_paid': int(loc.get('local_paid') or 0),
            'local_total': loc_total,
            'match_pct': match_pct,
            'missing_estimate': missing,
            'status': status,
        })

    out.sort(key=lambda x: (x['status'] != 'partial', x['status'] != 'missing', -x['missing_estimate']))
    return {
        'day': day,
        'source_unavailable': False,
        'affiliates': out,
        'partial_count': sum(1 for a in out if a['status'] in ('partial', 'missing')),
    }


def merge_reconciliation_into_coverage(
    coverage_report: dict,
    reconciliation_by_day: dict,
    *,
    threshold_pct: float = 99.5,
) -> dict:
    """Attach MCP reconciliation fields and upgrade refetch/stage when source mismatch."""
    daily = coverage_report.get('daily') or []
    refetch = {r['day']: r for r in (coverage_report.get('refetch_days') or [])}

    for row in daily:
        day = row['day']
        rec = reconciliation_by_day.get(day) or {}
        row['source_expected_free'] = rec.get('source_expected_free')
        row['source_expected_paid'] = rec.get('source_expected_paid')
        row['source_expected_total'] = rec.get('source_expected_total')
        row['local_match_pct'] = rec.get('local_match_pct')
        row['reconciliation_status'] = rec.get('reconciliation_status', 'unknown')
        row['reconciliation_checked_at'] = rec.get('reconciliation_checked_at')

        rstatus = row['reconciliation_status']
        if rstatus in ('partial', 'missing'):
            row['pipeline_stage'] = 'partial_source_match'
            if day not in refetch:
                refetch[day] = {
                    'day': day,
                    'reason': 'mcp_source_mismatch',
                    'reconciliation_status': rstatus,
                    'local_match_pct': row.get('local_match_pct'),
                    'source_expected_total': row.get('source_expected_total'),
                    'fetched_total': row.get('fetched_total'),
                }
        elif rstatus == 'source_unavailable' and row.get('pipeline_stage') == 'not_fetched':
            pass
        elif rstatus == 'source_unavailable' and not row.get('reconciliation_checked_at'):
            row['pipeline_stage'] = row.get('pipeline_stage') or 'needs_mcp_check'

    refetch_days = sorted(refetch.values(), key=lambda x: x['day'])
    coverage_report['refetch_days'] = refetch_days
    coverage_report['refetch_day_list'] = [d['day'] for d in refetch_days]
    coverage_report['refetch_count'] = len(refetch_days)
    mcp_partial = [
        d for d in daily
        if d.get('reconciliation_status') in ('partial', 'missing')
    ]
    coverage_report['mcp_partial_days'] = mcp_partial
    coverage_report['mcp_partial_count'] = len(mcp_partial)
    coverage_report['daily'] = daily
    return coverage_report
