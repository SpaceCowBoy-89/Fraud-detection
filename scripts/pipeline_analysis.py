"""
Shared fetch-window fraud analysis used by scheduler, webhook, and dashboard.

Canonical entry point: ``analyze_dataframe``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional


def iter_days_in_range(start_date: str, end_date: str):
    """Yield YYYY-MM-DD for each calendar day in [start_date, end_date]."""
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    cur = start
    while cur <= end:
        yield cur.strftime('%Y-%m-%d')
        cur += timedelta(days=1)


def _row_get(row: dict, *keys, default=None):
    """First non-empty value among keys in a plain dict row."""
    for key in keys:
        if key not in row:
            continue
        val = row[key]
        if val is None:
            continue
        try:
            import pandas as pd
            if pd.isna(val):
                continue
        except Exception:
            pass
        if isinstance(val, str) and val.strip() == '':
            continue
        return val
    return default


def analyze_dataframe(
    db,
    config,
    data_type,
    df,
    *,
    min_duid=None,
    include_house_in_analysis: bool = False,
    skip_affiliate_codes=None,
    return_results: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    mark_skipped_analyzed: bool = True,
):
    """
    Preprocess + score rows in df, write fraud_results, mark source rows analyzed.

    Args:
        min_duid: Optional DUID floor (defaults to config min_duid_threshold).
        include_house_in_analysis: Passed to affiliate skip-code resolution.
        skip_affiliate_codes: Optional explicit lowercase set; overrides config.
        return_results: Include per-row summary dicts in the return value.
        progress_cb: Optional ``(processed, total)`` callback during scoring.
        mark_skipped_analyzed: Mark house/old/empty-email rows analyzed so drains progress.

    Returns:
        dict with analyzed, skipped, high_risk counts (and optional results list).
    """
    import pandas as pd

    if df is None or df.empty:
        out = {'analyzed': 0, 'skipped': 0, 'high_risk': 0}
        if return_results:
            out['results'] = []
        return out

    from data_preprocessor import DataPreprocessor
    from email_fraud_detector import EmailFraudDetector

    if min_duid is None:
        min_duid = int(config.get('min_duid_threshold', 0) or 0)

    preprocessor = DataPreprocessor()
    df, _quality = preprocessor.preprocess_batch(df.copy())

    detector = EmailFraudDetector(config)
    df = detector.normalize_column_names(df)
    detector.build_repeated_word_map(df)
    detector.build_geographic_cluster_maps(df)
    detector.build_shared_ip_map(df, db=db)
    detector.build_ip_velocity_map(df, db=db)
    detector.build_gender_concentration_map(df)
    detector.build_sequential_email_map(df)
    detector.build_affiliate_domain_concentration_map(df)

    results = []
    skipped_duids = []
    email_col = detector.column_map.get('email') or 'email'
    high_th = int(config.get_risk_threshold('high') or 50)

    if skip_affiliate_codes is not None:
        skip_codes = {str(c).strip().lower() for c in skip_affiliate_codes if c}
    else:
        skip_codes = config.get_affiliate_analysis_skip_codes_lower(
            include_house_in_analysis=include_house_in_analysis
        )

    # to_dict('records') is much faster than DataFrame.iterrows() for large batches
    records = df.to_dict(orient='records')
    total = len(records)

    for processed, row in enumerate(records, start=1):
        if progress_cb and (processed % 100 == 0 or processed == total):
            try:
                progress_cb(processed, total)
            except Exception:
                pass

        duid_val = _row_get(row, 'duid', 'DUID')
        if duid_val is None or str(duid_val).strip() == '':
            continue

        if min_duid:
            try:
                if int(duid_val) < int(min_duid):
                    skipped_duids.append(duid_val)
                    continue
            except (ValueError, TypeError):
                pass

        webmaster_code = _row_get(row, 'webmaster_code', 'site_code')
        if skip_codes and webmaster_code and str(webmaster_code).strip().lower() in skip_codes:
            skipped_duids.append(duid_val)
            continue

        campaign = _row_get(row, 'campaign')

        email = row.get(email_col) if email_col else None
        if email is None:
            email = _row_get(row, 'email', 'Email')
        if not email or str(email).lower() in ('', 'nan', 'none'):
            skipped_duids.append(duid_val)
            continue

        analysis = detector.analyze_email(
            email,
            trans_datetime=_row_get(row, 'trans_datetime'),
            pov_verified=_row_get(row, 'pov_verified'),
            pov_verified_time=_row_get(row, 'pov_verified_time'),
            ip_address=_row_get(row, 'ip'),
            user_agent=_row_get(row, 'custom_http_user_agent', 'user_agent'),
            first_name=_row_get(row, 'first_name'),
            user1=_row_get(row, 'custom_u1', 'user1'),
        )
        analysis['DUID'] = duid_val
        analysis['payout_amount'] = _row_get(row, 'payout_amount', default=0) or 0
        analysis['data_type'] = data_type
        analysis['webmaster_code'] = webmaster_code
        analysis['campaign'] = campaign
        analysis['ad_id'] = _row_get(row, 'ad_id', 'ad')
        analysis['trans_datetime'] = _row_get(row, 'trans_datetime')
        analysis['pov_verified'] = _row_get(row, 'pov_verified')
        analysis['pov_verified_time'] = _row_get(row, 'pov_verified_time')
        analysis['user_agent'] = _row_get(row, 'custom_http_user_agent', 'user_agent')
        src_geo = _row_get(row, 'geo_country')
        analysis['geo_country'] = src_geo or analysis.get('geo_country')
        analysis['ip'] = _row_get(row, 'ip')
        analysis['first_name'] = _row_get(row, 'first_name')
        analysis['custom_u1'] = _row_get(row, 'custom_u1', 'user1')
        results.append(analysis)

    if results:
        detector.apply_gender_concentration_to_results(results)
        detector.apply_sequential_email_to_results(results)
        detector.apply_affiliate_domain_concentration_to_results(results)
        db.save_fraud_results(results)
        duids = [r['DUID'] for r in results if r.get('DUID') not in (None, '', 'N/A')]
        if duids:
            db.mark_as_analyzed(duids, data_type)

    # House affiliates, old DUIDs, and rows without email are excluded from scoring
    # but must be marked analyzed so backlog drain does not stall on them.
    if mark_skipped_analyzed and skipped_duids:
        db.mark_as_analyzed(skipped_duids, data_type)

    out = {
        'analyzed': len(results),
        'skipped': len(skipped_duids),
        'high_risk': sum(1 for r in results if r.get('risk_score', 0) >= high_th),
    }
    if return_results:
        out['results'] = [
            {
                'duid': r.get('DUID'),
                'email': r.get('email'),
                'risk_score': r.get('risk_score'),
                'flags': r.get('flags'),
            }
            for r in results
        ]
    return out


def drain_unanalyzed_for_day(
    db,
    config,
    day: str,
    *,
    batch_limit: int = 5000,
    max_batches: int = 20,
    paid_first: bool = True,
):
    """
    Batch-analyze remaining unanalyzed source rows for one calendar day.

    Loops until the day is drained or max_batches is reached.
    """
    batch_limit = max(200, min(int(batch_limit), 50_000))
    max_batches = max(1, min(int(max_batches), 200))
    type_order = ('paid', 'free') if paid_first else ('free', 'paid')
    per_type_limit = max(100, batch_limit // 2)

    total_analyzed = 0
    total_high = 0
    batches_run = 0

    for _ in range(max_batches):
        pending = db.count_unanalyzed_for_day(day)
        if pending < 1:
            break

        batch_analyzed = 0
        for data_type in type_order:
            df = db.get_unanalyzed_records_for_day(data_type, day, limit=per_type_limit)
            if df.empty:
                continue
            summary = analyze_dataframe(db, config, data_type, df)
            processed = int(summary.get('analyzed') or 0) + int(summary.get('skipped') or 0)
            batch_analyzed += processed
            total_analyzed += int(summary.get('analyzed') or 0)
            total_high += int(summary.get('high_risk') or 0)

        batches_run += 1
        if batch_analyzed < 1:
            break

    remaining = db.count_unanalyzed_for_day(day)
    return {
        'day': day,
        'analyzed': total_analyzed,
        'high_risk': total_high,
        'batches': batches_run,
        'remaining': remaining,
        'complete': remaining < 1,
    }


def drain_unanalyzed_for_range(
    db,
    config,
    start_date: str,
    end_date: str,
    **kwargs,
):
    """Drain unanalyzed rows for each day in the date range."""
    days = list(iter_days_in_range(start_date, end_date))
    per_day = []
    total_analyzed = 0
    total_high = 0
    for day in days:
        if db.count_unanalyzed_for_day(day) < 1:
            continue
        summary = drain_unanalyzed_for_day(db, config, day, **kwargs)
        per_day.append(summary)
        total_analyzed += int(summary.get('analyzed') or 0)
        total_high += int(summary.get('high_risk') or 0)
    return {
        'start_date': start_date,
        'end_date': end_date,
        'days': per_day,
        'analyzed': total_analyzed,
        'high_risk': total_high,
    }
