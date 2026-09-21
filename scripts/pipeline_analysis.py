"""
Shared fetch-window fraud analysis used by scheduler backlog drain and webhooks.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def iter_days_in_range(start_date: str, end_date: str):
    """Yield YYYY-MM-DD for each calendar day in [start_date, end_date]."""
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    cur = start
    while cur <= end:
        yield cur.strftime('%Y-%m-%d')
        cur += timedelta(days=1)


def analyze_dataframe(db, config, data_type, df, *, min_duid=None):
    """
    Preprocess + score rows in df, write fraud_results, mark source rows analyzed.

    Returns dict with analyzed, high_risk counts.
    """
    import pandas as pd

    if df is None or df.empty:
        return {'analyzed': 0, 'high_risk': 0}

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
    email_col = detector.column_map.get('email')
    high_th = int(config.get_risk_threshold('high') or 50)
    skip_codes = config.get_affiliate_analysis_skip_codes_lower(
        include_house_in_analysis=False
    )

    for _idx, row in df.iterrows():
        duid_val = detector.get_column(row, 'duid', None)
        if duid_val is None or str(duid_val).strip() == '':
            continue

        if min_duid:
            try:
                if int(duid_val) < min_duid:
                    skipped_duids.append(duid_val)
                    continue
            except (ValueError, TypeError):
                pass

        webmaster_code = detector.get_column(row, 'webmaster_code', None)
        if not webmaster_code:
            for col in ('webmaster_code', 'site_code'):
                if col in row.index and pd.notna(row[col]) and row[col] != '':
                    webmaster_code = row[col]
                    break
        if skip_codes and webmaster_code and str(webmaster_code).strip().lower() in skip_codes:
            skipped_duids.append(duid_val)
            continue

        campaign = detector.get_column(row, 'campaign', None)
        if not campaign and 'campaign' in row.index and pd.notna(row['campaign']):
            campaign = row['campaign']

        email = row.get(email_col) if email_col else None
        if not email or str(email).lower() in ('', 'nan', 'none'):
            skipped_duids.append(duid_val)
            continue

        analysis = detector.analyze_email(
            email,
            trans_datetime=detector.get_column(row, 'trans_datetime', None),
            pov_verified=detector.get_column(row, 'pov_verified', None),
            pov_verified_time=detector.get_column(row, 'pov_verified_time', None),
            ip_address=detector.get_column(row, 'ip', None),
            user_agent=detector.get_column(row, 'custom_http_user_agent', None),
            first_name=detector.get_column(row, 'first_name', None),
            user1=(
                detector.get_column(row, 'custom_u1', None)
                or detector.get_column(row, 'user1', None)
            ),
        )
        analysis['DUID'] = duid_val
        analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
        analysis['data_type'] = data_type
        analysis['webmaster_code'] = webmaster_code
        analysis['campaign'] = campaign
        analysis['ad_id'] = detector.get_column(row, 'ad_id', None)
        analysis['trans_datetime'] = detector.get_column(row, 'trans_datetime', None)
        analysis['pov_verified'] = detector.get_column(row, 'pov_verified', None)
        analysis['pov_verified_time'] = detector.get_column(row, 'pov_verified_time', None)
        analysis['user_agent'] = detector.get_column(row, 'custom_http_user_agent', None)
        src_geo = detector.get_column(row, 'geo_country', None)
        analysis['geo_country'] = src_geo or analysis.get('geo_country')
        analysis['ip'] = detector.get_column(row, 'ip', None)
        analysis['first_name'] = detector.get_column(row, 'first_name', None)
        analysis['custom_u1'] = (
            detector.get_column(row, 'custom_u1', None)
            or detector.get_column(row, 'user1', None)
        )
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
    if skipped_duids:
        db.mark_as_analyzed(skipped_duids, data_type)

    return {
        'analyzed': len(results),
        'skipped': len(skipped_duids),
        'high_risk': sum(1 for r in results if r.get('risk_score', 0) >= high_th),
    }


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
