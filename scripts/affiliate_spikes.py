"""
Per-affiliate volume spike detection (hybrid MCP + local, event-date based).

Mirrors volume_anomalies hybrid mode:
- Score on PS7/MCP source counts by trans_date when available
- Fall back to local free/paid counts by trans_datetime
- Exclude current calendar day (incomplete vs full-day baseline)
- Exclude partial-fetch days when scoring locally only
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

BASELINE_WINDOW = 14
MIN_BASELINE_DAYS = 3


def _pct_above(count: float, baseline: float) -> Optional[float]:
    if baseline is None or baseline <= 0:
        return None
    return round((float(count) - float(baseline)) / float(baseline) * 100, 1)


def _classify_level(z: float, count: float, b_mean: float) -> Optional[str]:
    if z >= 3.0:
        return 'severe'
    if z >= 2.0 or (b_mean > 0 and count >= b_mean * 2):
        return 'spike'
    return None


def get_affiliate_spike_config(config) -> dict:
    """Reuse volume_anomalies hybrid knobs."""
    try:
        from volume_anomalies import get_volume_anomaly_config
        return get_volume_anomaly_config(config)
    except ImportError:
        sched = (config.get('scheduler') or {}) if isinstance(config, dict) else {}
        va = sched.get('volume_anomalies') or {}
        return {
            'match_threshold_pct': float(va.get('match_threshold_pct', 99.5) or 99.5),
            'prefer_source_counts': bool(va.get('prefer_source_counts', True)),
            'exclude_today': bool(va.get('exclude_today', True)),
        }


def _fetch_source_affiliate_daily(config, start_date: str, end_date: str) -> dict:
    try:
        from source_reconciliation import (
            NullSourceClient,
            build_source_client,
            reconciliation_source_configured,
        )
    except ImportError:
        return {}

    if not reconciliation_source_configured(config):
        return {}

    try:
        client = build_source_client(config)
        if isinstance(client, NullSourceClient):
            return {}
        return client.query_affiliate_daily_counts(start_date, end_date) or {}
    except Exception as exc:
        logger.warning('Affiliate spike source query failed: %s', exc)
        return {}


def _day_completeness(
    day: str,
    local_total: int,
    source_day_total: Optional[int],
    rec: dict,
    threshold: float,
) -> Tuple[Optional[float], Optional[bool], Optional[str]]:
    """Return (match_pct, local_complete, reconciliation_status)."""
    from source_reconciliation import compute_match_status

    if rec.get('local_match_pct') is not None:
        match_pct = float(rec['local_match_pct'])
        rec_status = rec.get('reconciliation_status')
        local_complete = rec_status == 'complete' or match_pct >= threshold
        return match_pct, local_complete, rec_status

    if source_day_total is not None and source_day_total > 0:
        _, match_status = compute_match_status(
            source_day_total, local_total, threshold_pct=threshold,
        )
        match_pct = round(100.0 * local_total / max(source_day_total, 1), 2)
        return match_pct, match_status == 'complete', match_status

    return None, None, rec.get('reconciliation_status')


def detect_affiliate_spikes(
    db,
    config,
    lookback_days: int = 30,
    min_z: float = 2.0,
    min_count: int = 5,
    level_filter: str = 'all',
    sort_key: str = 'z_score',
) -> dict:
    """
    Detect per-affiliate spikes using hybrid MCP/local event-date counts.

    Returns spikes list (unpaginated), excluded list, hybrid info, summary.
    """
    lookback_days = max(7, min(int(lookback_days), 90))
    min_count = max(1, int(min_count))
    level_filter = (level_filter or 'all').strip().lower()
    sort_key = (sort_key or 'z_score').strip().lower()

    va_cfg = get_affiliate_spike_config(config)
    threshold = float(va_cfg['match_threshold_pct'])
    prefer_source = bool(va_cfg['prefer_source_counts'])
    exclude_today = bool(va_cfg['exclude_today'])
    today_str = date.today().isoformat()

    end = date.today()
    start = end - timedelta(days=lookback_days + BASELINE_WINDOW + 1)
    start_date, end_date = start.isoformat(), end.isoformat()
    cutoff = (end - timedelta(days=lookback_days - 1)).isoformat()

    local_rows = db.get_local_affiliate_daily_counts(start_date, end_date)
    risk_map = db.get_affiliate_risk_daily(start_date, end_date)
    rec_by_day = db.get_reconciliation_results(start_date, end_date)

    source_by_day_aff: Dict[str, Dict[str, Dict[str, int]]] = {}
    if prefer_source:
        source_by_day_aff = _fetch_source_affiliate_daily(config, start_date, end_date)
    live_source = bool(source_by_day_aff)

    # Local index: affiliate -> [{day, free, paid, total}]
    local_by_aff: Dict[str, Dict[str, dict]] = {}
    local_day_totals: Dict[str, int] = {}
    display_code: Dict[str, str] = {}
    for row in local_rows:
        aff = row['affiliate']
        day = row['day']
        display_code.setdefault(aff, aff)
        local_by_aff.setdefault(aff, {})[day] = row
        local_day_totals[day] = local_day_totals.get(day, 0) + int(row['local_total'])

    # Source day totals for completeness
    source_day_totals: Dict[str, int] = {}
    for day, affs in source_by_day_aff.items():
        source_day_totals[day] = sum(int(v.get('total') or 0) for v in affs.values())
        for aff in affs:
            display_code.setdefault(aff, aff)

    day_meta: Dict[str, dict] = {}
    all_days = sorted(set(local_day_totals) | set(source_day_totals) | set(rec_by_day))
    for day in all_days:
        loc_t = int(local_day_totals.get(day, 0))
        src_t = source_day_totals.get(day)
        rec = rec_by_day.get(day, {})
        match_pct, local_complete, rec_status = _day_completeness(
            day, loc_t, src_t, rec, threshold,
        )
        source_used = prefer_source and day in source_by_day_aff
        day_in_progress = bool(exclude_today and day == today_str)
        day_meta[day] = {
            'local_total': loc_t,
            'source_total': src_t,
            'local_match_pct': match_pct,
            'local_data_complete': local_complete if local_complete is not None else True,
            'source_used_for_scoring': source_used,
            'partial_fetch': local_complete is False,
            'day_in_progress': day_in_progress,
            'reconciliation_status': rec_status or rec.get('reconciliation_status'),
        }

    # All affiliates seen in local or source
    all_affs = sorted(set(local_by_aff) | {
        aff for day_affs in source_by_day_aff.values() for aff in day_affs
    })

    spikes: List[dict] = []
    excluded: List[dict] = []

    for aff in all_affs:
        # Build observation series (sorted days with a score count)
        observations: List[Tuple[str, float, int, int]] = []  # day, score, local, source
        days_set = set(local_by_aff.get(aff, {})) | {
            d for d, affs in source_by_day_aff.items() if aff in affs
        }
        for day in sorted(days_set):
            loc = local_by_aff.get(aff, {}).get(day, {})
            loc_total = int(loc.get('local_total') or 0)
            src = (source_by_day_aff.get(day) or {}).get(aff)
            src_total = int(src.get('total') or 0) if src else None
            meta = day_meta.get(day, {})
            if meta.get('source_used_for_scoring'):
                if src is None:
                    continue
                score = float(src_total or 0)
            else:
                score = float(loc_total)
            if score <= 0:
                continue
            observations.append((
                day,
                score,
                loc_total,
                int(src_total) if src_total is not None else -1,
            ))

        if len(observations) < MIN_BASELINE_DAYS + 1:
            continue

        for i, (day, score, loc_total, src_total_or_neg) in enumerate(observations):
            if day < cutoff:
                continue
            if score < min_count:
                continue

            prior = [observations[j][1] for j in range(i)][-BASELINE_WINDOW:]
            if len(prior) < MIN_BASELINE_DAYS:
                continue

            b_mean = float(np.mean(prior))
            b_std = float(np.std(prior, ddof=1)) if len(prior) > 1 else 0.0
            if b_std > 0:
                z = (score - b_mean) / b_std
            elif b_mean > 0 and score >= b_mean * 2:
                z = 2.5
            else:
                z = 0.0

            if z < min_z and not (b_mean > 0 and score >= b_mean * 2):
                continue

            level = _classify_level(z, score, b_mean)
            if not level:
                continue
            if level_filter == 'severe' and level != 'severe':
                continue
            if level_filter == 'spike' and level not in ('spike', 'severe'):
                continue

            meta = day_meta.get(day, {})
            risk = risk_map.get((aff, day), {})
            src_total = None if src_total_or_neg < 0 else src_total_or_neg
            row = {
                'webmaster_code': display_code.get(aff, aff),
                'spike_date': day,
                'count': int(score),
                'local_count': loc_total,
                'source_count': src_total,
                'high_risk': int(risk.get('high_risk') or 0),
                'avg_risk': risk.get('avg_risk'),
                'payout_at_risk': float(risk.get('payout_at_risk') or 0),
                'analyzed': int(risk.get('analyzed') or 0),
                'baseline_avg': round(b_mean, 1),
                'baseline_days': len(prior),
                'z_score': round(float(z), 2),
                'pct_above': _pct_above(score, b_mean),
                'spike_level': level,
                'partial_fetch': bool(meta.get('partial_fetch')),
                'day_in_progress': bool(meta.get('day_in_progress')),
                'source_used_for_scoring': bool(meta.get('source_used_for_scoring')),
                'local_match_pct': meta.get('local_match_pct'),
                'local_data_complete': meta.get('local_data_complete'),
                'reconciliation_status': meta.get('reconciliation_status'),
            }

            if meta.get('day_in_progress'):
                row['excluded_reason'] = 'day_in_progress'
                excluded.append(row)
                continue
            if (
                not meta.get('source_used_for_scoring')
                and meta.get('local_data_complete') is False
            ):
                row['excluded_reason'] = 'partial_fetch'
                excluded.append(row)
                continue

            spikes.append(row)

    if sort_key == 'date':
        spikes.sort(key=lambda s: (s.get('spike_date') or '', s.get('z_score') or 0), reverse=True)
    elif sort_key == 'count':
        spikes.sort(key=lambda s: (-(s.get('count') or 0), -(s.get('z_score') or 0)))
    elif sort_key == 'pct_above':
        spikes.sort(key=lambda s: (-(s.get('pct_above') or 0), -(s.get('z_score') or 0)))
    else:
        spikes.sort(key=lambda s: (-(s.get('z_score') or 0), s.get('spike_date') or ''))

    severe_n = sum(1 for s in spikes if s['spike_level'] == 'severe')
    spike_n = sum(1 for s in spikes if s['spike_level'] == 'spike')

    return {
        'spikes': spikes,
        'excluded_spikes': excluded,
        'summary': {
            'total': len(spikes),
            'severe': severe_n,
            'spike': spike_n,
            'excluded': len(excluded),
        },
        'hybrid': {
            'source_available': live_source or bool(rec_by_day),
            'counts_source': (
                'mcp' if live_source
                else ('reconciliation_cache' if rec_by_day else 'local')
            ),
            'match_threshold_pct': threshold,
            'prefer_source_counts': prefer_source,
            'exclude_today': exclude_today,
            'start_date': start_date,
            'end_date': end_date,
            'date_field': 'trans_datetime',
        },
        'lookback_days': lookback_days,
        'min_count': min_count,
        'min_z': min_z,
        'sort': sort_key,
        'level': level_filter,
    }


def paginate_spikes(result: dict, page: int = 1, per_page: int = 20) -> dict:
    """Attach pagination slice to a detect_affiliate_spikes result."""
    spikes = result.get('spikes') or []
    per_page = min(max(int(per_page), 1), 100)
    page = max(int(page), 1)
    total = len(spikes)
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    offset = (page - 1) * per_page
    out = dict(result)
    out['spikes'] = spikes[offset:offset + per_page]
    out['pagination'] = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
    }
    return out
