"""
Business volume anomaly detection: registration and sales surges/dips.

Uses event dates (trans_datetime) rather than analyzed_at so catch-up imports
do not create false spikes.

Hybrid mode (when MCP/PS7 source is configured): z-scores use source counts;
days with incomplete local fetch are excluded from the anomaly list unless
source counts were used for scoring.

The current calendar day is excluded from anomaly signals by default (partial
day vs full-day baseline would otherwise look like a severe dip/surge).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROLLING_WINDOW = 14
MIN_PERIODS = 7
SURGE_SPIKE = 2.0
SURGE_SEVERE = 3.0
ELEVATED = 1.5

ANOMALY_LEVELS = frozenset({
    'surge', 'surge_severe', 'dip', 'dip_severe',
})


def classify_z(z) -> str:
    """Bidirectional z-score classification."""
    if z is None or (isinstance(z, float) and np.isnan(z)):
        return 'normal'
    z = float(z)
    if z >= SURGE_SEVERE:
        return 'surge_severe'
    if z >= SURGE_SPIKE:
        return 'surge'
    if z >= ELEVATED:
        return 'elevated_up'
    if z <= -SURGE_SEVERE:
        return 'dip_severe'
    if z <= -SURGE_SPIKE:
        return 'dip'
    if z <= -ELEVATED:
        return 'elevated_down'
    return 'normal'


def _rolling_z(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    rolling_mean = (
        series.rolling(window=ROLLING_WINDOW, min_periods=MIN_PERIODS, center=False)
        .mean()
        .shift(1)
    )
    rolling_std = (
        series.rolling(window=ROLLING_WINDOW, min_periods=MIN_PERIODS, center=False)
        .std()
        .shift(1)
    )
    z_vals = []
    for actual, mean, std in zip(series, rolling_mean, rolling_std):
        if std is not None and not pd.isna(std) and std > 0 and mean is not None and not pd.isna(mean):
            z_vals.append((float(actual) - float(mean)) / float(std))
        elif mean is not None and not pd.isna(mean) and float(mean) > 0:
            ratio = float(actual) / float(mean)
            if ratio >= 2.0:
                z_vals.append(2.5)
            elif ratio <= 0.5:
                z_vals.append(-2.5)
            else:
                z_vals.append(np.nan)
        else:
            z_vals.append(np.nan)
    return rolling_mean, rolling_std, pd.Series(z_vals, index=series.index)


def _pct_above(actual, baseline):
    if baseline is None or baseline == 0 or pd.isna(baseline):
        return None
    return round((float(actual) - float(baseline)) / float(baseline) * 100, 1)


def _safe_int(val) -> int:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 0
    return int(val)


def _safe_float(val, ndigits=2):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), ndigits)


def analyze_volume_anomalies(
    reg_df: pd.DataFrame,
    sales_df: pd.DataFrame,
) -> dict:
    """
    Merge daily registration and sales counts, compute rolling z-scores.

    reg_df columns: day, registrations
    sales_df columns: day, sales
    """
    reg = reg_df.copy() if reg_df is not None and not reg_df.empty else pd.DataFrame(columns=['day', 'registrations'])
    sal = sales_df.copy() if sales_df is not None and not sales_df.empty else pd.DataFrame(columns=['day', 'sales'])

    if not reg.empty:
        reg['day'] = reg['day'].astype(str)
        reg['registrations'] = reg['registrations'].fillna(0).astype(int)
    if not sal.empty:
        sal['day'] = sal['day'].astype(str)
        sal['sales'] = sal['sales'].fillna(0).astype(int)

    if reg.empty and sal.empty:
        return {'daily': [], 'anomalies': [], 'baseline': {}}

    df = pd.merge(reg, sal, on='day', how='outer').sort_values('day').reset_index(drop=True)
    df['registrations'] = df['registrations'].fillna(0).astype(int)
    df['sales'] = df['sales'].fillna(0).astype(int)

    reg_mean, _, reg_z = _rolling_z(df['registrations'].astype(float))
    sal_mean, _, sal_z = _rolling_z(df['sales'].astype(float))

    df['reg_rolling_mean'] = reg_mean
    df['sales_rolling_mean'] = sal_mean
    df['registration_z'] = reg_z.round(2)
    df['sales_z'] = sal_z.round(2)
    df['registration_level'] = df['registration_z'].apply(classify_z)
    df['sales_level'] = df['sales_z'].apply(classify_z)
    df['conversion_rate'] = np.where(
        df['registrations'] > 0,
        (df['sales'] / df['registrations'] * 100).round(2),
        np.nan,
    )

    daily = []
    anomalies = []

    for _, row in df.iterrows():
        conv = row['conversion_rate']
        daily.append({
            'date': row['day'],
            'registrations': _safe_int(row['registrations']),
            'sales': _safe_int(row['sales']),
            'conversion_rate': _safe_float(conv) if not pd.isna(conv) else None,
            'registration_z': _safe_float(row['registration_z']),
            'sales_z': _safe_float(row['sales_z']),
            'reg_rolling_mean': _safe_float(row['reg_rolling_mean'], 1),
            'sales_rolling_mean': _safe_float(row['sales_rolling_mean'], 1),
            'registration_level': row['registration_level'],
            'sales_level': row['sales_level'],
        })

        reg_lvl = row['registration_level']
        sal_lvl = row['sales_level']
        if reg_lvl in ANOMALY_LEVELS or sal_lvl in ANOMALY_LEVELS:
            anomalies.append({
                'date': row['day'],
                'registrations': _safe_int(row['registrations']),
                'sales': _safe_int(row['sales']),
                'conversion_rate': _safe_float(conv) if not pd.isna(conv) else None,
                'registration_z': _safe_float(row['registration_z']),
                'sales_z': _safe_float(row['sales_z']),
                'registration_level': reg_lvl,
                'sales_level': sal_lvl,
                'reg_pct_vs_baseline': _pct_above(row['registrations'], row['reg_rolling_mean']),
                'sales_pct_vs_baseline': _pct_above(row['sales'], row['sales_rolling_mean']),
            })

    anomalies.sort(key=lambda x: x['date'], reverse=True)

    return {
        'daily': daily,
        'anomalies': anomalies,
        'baseline': {
            'registrations_mean': _safe_float(df['registrations'].mean(), 1),
            'registrations_std': _safe_float(df['registrations'].std(), 1),
            'sales_mean': _safe_float(df['sales'].mean(), 1),
            'sales_std': _safe_float(df['sales'].std(), 1),
            'days': len(df),
        },
    }


def get_volume_anomaly_config(config) -> dict:
    """Merge volume_anomalies settings with mcp_reconciliation defaults."""
    sched = config.get('scheduler', {}) or {}
    va = sched.get('volume_anomalies') or config.get('volume_anomalies') or {}
    rc = sched.get('mcp_reconciliation') or {}
    if not isinstance(va, dict):
        va = {}
    threshold = float(
        va.get('match_threshold_pct')
        or rc.get('match_threshold_pct', 99.5)
        or 99.5
    )
    return {
        'match_threshold_pct': threshold,
        'prefer_source_counts': bool(va.get('prefer_source_counts', True)),
        'exclude_today': bool(va.get('exclude_today', True)),
    }


def _date_range_for_lookback(lookback_days: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=max(1, lookback_days) - 1)
    return start.isoformat(), end.isoformat()


def load_local_daily_counts(db, lookback_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily free/paid counts from local SQLite by trans_datetime."""
    cutoff = f'-{lookback_days} days'
    reg_q = """
        SELECT DATE(trans_datetime) AS day, COUNT(*) AS registrations
        FROM free
        WHERE trans_datetime IS NOT NULL
          AND trans_datetime >= DATE('now', :cutoff)
        GROUP BY day
        ORDER BY day
    """
    sales_q = """
        SELECT DATE(trans_datetime) AS day, COUNT(*) AS sales
        FROM paid
        WHERE trans_datetime IS NOT NULL
          AND trans_datetime >= DATE('now', :cutoff)
        GROUP BY day
        ORDER BY day
    """
    with db.get_connection() as conn:
        reg_df = pd.read_sql_query(reg_q, conn, params={'cutoff': cutoff})
        sales_df = pd.read_sql_query(sales_q, conn, params={'cutoff': cutoff})
    return reg_df, sales_df


def _fetch_source_daily_counts(config, start_date: str, end_date: str) -> dict:
    """Live MCP/ES daily counts; returns {} when unavailable."""
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
        return client.query_daily_counts(start_date, end_date) or {}
    except Exception as exc:
        logger.warning('Volume anomaly source query failed: %s', exc)
        return {}


def build_hybrid_volume_series(
    db,
    config,
    lookback_days: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """
    Build scoring series (MCP when available, else local) plus per-day metadata.

    Returns (reg_df, sales_df, day_meta_by_date, info).
    """
    from source_reconciliation import compute_match_status

    va_cfg = get_volume_anomaly_config(config)
    threshold = va_cfg['match_threshold_pct']
    prefer_source = va_cfg['prefer_source_counts']
    exclude_today = va_cfg['exclude_today']
    today_str = date.today().isoformat()
    start_date, end_date = _date_range_for_lookback(lookback_days)

    reg_df, sales_df = load_local_daily_counts(db, lookback_days)
    local_reg = (
        dict(zip(reg_df['day'].astype(str), reg_df['registrations']))
        if not reg_df.empty else {}
    )
    local_sal = (
        dict(zip(sales_df['day'].astype(str), sales_df['sales']))
        if not sales_df.empty else {}
    )

    rec_by_day = db.get_reconciliation_results(start_date, end_date)
    source_by_day = _fetch_source_daily_counts(config, start_date, end_date) if prefer_source else {}
    live_source = bool(source_by_day)

    for day, rec in rec_by_day.items():
        if day in source_by_day:
            continue
        exp_total = rec.get('source_expected_total')
        if exp_total is None:
            continue
        source_by_day[day] = {
            'free': int(rec.get('source_expected_free') or 0),
            'paid': int(rec.get('source_expected_paid') or 0),
            'total': int(exp_total or 0),
        }

    all_days = sorted(set(local_reg) | set(local_sal) | set(source_by_day))
    day_meta: dict = {}
    reg_rows = []
    sal_rows = []

    for day in all_days:
        loc_r = int(local_reg.get(day, 0))
        loc_s = int(local_sal.get(day, 0))
        src = source_by_day.get(day)
        rec = rec_by_day.get(day, {})

        src_r = src_s = None
        if src:
            src_r = int(src.get('free') or 0)
            src_s = int(src.get('paid') or 0)

        if rec.get('local_match_pct') is not None:
            match_pct = float(rec['local_match_pct'])
            rec_status = rec.get('reconciliation_status')
            local_complete = rec_status == 'complete' or match_pct >= threshold
        elif src_r is not None:
            _, match_status = compute_match_status(
                (src_r or 0) + (src_s or 0),
                loc_r + loc_s,
                threshold_pct=threshold,
            )
            match_pct = round(
                100.0 * (loc_r + loc_s) / max((src_r or 0) + (src_s or 0), 1), 2
            ) if ((src_r or 0) + (src_s or 0)) > 0 else None
            local_complete = match_status == 'complete'
        else:
            match_pct = None
            local_complete = None

        source_used = src_r is not None and prefer_source
        score_r = src_r if source_used else loc_r
        score_s = src_s if source_used else loc_s

        reg_rows.append({'day': day, 'registrations': score_r})
        sal_rows.append({'day': day, 'sales': score_s})

        partial_fetch = local_complete is False
        day_in_progress = bool(exclude_today and day == today_str)
        day_meta[day] = {
            'local_registrations': loc_r,
            'local_sales': loc_s,
            'source_registrations': src_r,
            'source_sales': src_s,
            'local_match_pct': match_pct,
            'local_data_complete': local_complete if local_complete is not None else True,
            'source_used_for_scoring': source_used,
            'partial_fetch': partial_fetch,
            'day_in_progress': day_in_progress,
            'reconciliation_status': rec.get('reconciliation_status'),
        }

    info = {
        'source_available': live_source or bool(rec_by_day),
        'counts_source': (
            'mcp' if live_source
            else ('reconciliation_cache' if rec_by_day else 'local')
        ),
        'match_threshold_pct': threshold,
        'start_date': start_date,
        'end_date': end_date,
    }
    return (
        pd.DataFrame(reg_rows) if reg_rows else pd.DataFrame(columns=['day', 'registrations']),
        pd.DataFrame(sal_rows) if sal_rows else pd.DataFrame(columns=['day', 'sales']),
        day_meta,
        info,
    )


_DAY_META_FIELDS = (
    'local_registrations',
    'local_sales',
    'source_registrations',
    'source_sales',
    'local_match_pct',
    'local_data_complete',
    'source_used_for_scoring',
    'partial_fetch',
    'day_in_progress',
    'reconciliation_status',
)


def apply_hybrid_metadata(result: dict, day_meta: dict) -> dict:
    """Attach local/source fields to daily rows; filter incomplete-day false anomalies."""
    enriched_daily = []
    for row in result.get('daily') or []:
        meta = day_meta.get(row['date'], {})
        enriched = dict(row)
        for key in _DAY_META_FIELDS:
            if key in meta:
                enriched[key] = meta[key]
        # Don't label an open calendar day as surge/dip — baseline is full-day.
        if meta.get('day_in_progress'):
            enriched['registration_level'] = 'in_progress'
            enriched['sales_level'] = 'in_progress'
        enriched_daily.append(enriched)
    result['daily'] = enriched_daily

    filtered = []
    excluded = []
    for anomaly in result.get('anomalies') or []:
        meta = day_meta.get(anomaly['date'], {})
        enriched = dict(anomaly)
        for key in _DAY_META_FIELDS:
            if key in meta:
                enriched[key] = meta[key]
        if meta.get('day_in_progress'):
            enriched['excluded_reason'] = 'day_in_progress'
            enriched['registration_level'] = 'in_progress'
            enriched['sales_level'] = 'in_progress'
            excluded.append(enriched)
            continue
        if (
            not meta.get('source_used_for_scoring')
            and meta.get('local_data_complete') is False
        ):
            enriched['excluded_reason'] = 'partial_fetch'
            excluded.append(enriched)
            continue
        filtered.append(enriched)

    result['anomalies'] = filtered
    result['excluded_anomalies'] = excluded
    return result
