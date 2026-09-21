#!/usr/bin/env python3
"""
Daily source-table coverage audit.

Flags calendar days where free signup volume or distinct affiliate count drops
sharply vs the surrounding window — typical sign of failed/partial API fetches.

Usage:
    python scripts/coverage_audit.py
    python scripts/coverage_audit.py --start 2026-06-01 --end 2026-06-30
    python scripts/coverage_audit.py --affiliate marinagoodads
    python scripts/coverage_audit.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import Database  # noqa: E402


def _parse_day(s: str):
    return datetime.strptime(s, '%Y-%m-%d').date()


def _iter_days(start, end):
    cur = start
    while cur <= end:
        yield cur.strftime('%Y-%m-%d')
        cur += timedelta(days=1)


def detect_missing_fetch_days(
    db: Database,
    start_date: str,
    end_date: str,
    *,
    min_neighbor_rows: int = 1000,
):
    """
    Calendar days with zero fetched rows while at least one neighbor day has traffic.
    Catches VPN/API outage gaps (e.g. Jul 3–4 never fetched).
    """
    daily = db.get_daily_pipeline_coverage(start_date, end_date)
    if not daily:
        return {'missing_days': [], 'daily': [], 'start_date': start_date, 'end_date': end_date}

    totals = [int(d.get('fetched_total') or 0) for d in daily]
    missing = []
    for i, row in enumerate(daily):
        fetched = int(row.get('fetched_total') or 0)
        if fetched > 0:
            continue
        prev_ok = i > 0 and totals[i - 1] >= min_neighbor_rows
        next_ok = i < len(totals) - 1 and totals[i + 1] >= min_neighbor_rows
        if prev_ok or next_ok:
            missing.append({
                'day': row['day'],
                'reason': 'zero_rows_with_neighbor_traffic',
                'prev_day_rows': totals[i - 1] if i > 0 else 0,
                'next_day_rows': totals[i + 1] if i < len(totals) - 1 else 0,
            })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'missing_days': missing,
        'daily': daily,
        'pending_analysis_total': sum(int(d.get('pending_analysis') or 0) for d in daily),
    }


def detect_partial_fetch_days(
    db: Database,
    start_date: str,
    end_date: str,
    *,
    min_rows: int = 5000,
    ratio: float = 0.55,
    exclude_days=None,
):
    """
    Days with some fetched rows but volume far below the window median — partial API fetch.
    """
    exclude = set(exclude_days or [])
    daily = db.get_daily_pipeline_coverage(start_date, end_date)
    totals = [
        int(d.get('fetched_total') or 0)
        for d in daily
        if int(d.get('fetched_total') or 0) > 0
    ]
    if not totals:
        return {'partial_days': [], 'median_fetched': 0, 'daily': daily}

    median = sorted(totals)[len(totals) // 2]
    threshold = max(min_rows, int(median * ratio)) if median else min_rows
    partial = []
    for row in daily:
        day = row['day']
        if day in exclude:
            continue
        fetched = int(row.get('fetched_total') or 0)
        if fetched < 1 or fetched >= threshold:
            continue
        partial.append({
            'day': day,
            'reason': 'below_median_volume',
            'fetched_total': fetched,
            'median_fetched': median,
            'threshold': threshold,
        })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'partial_days': partial,
        'median_fetched': median,
        'threshold': threshold,
        'daily': daily,
    }


def detect_coverage_gaps(
    db: Database,
    start_date: str,
    end_date: str,
    *,
    min_neighbor_rows: int = 1000,
    detect_partial: bool = True,
    partial_min_rows: int = 5000,
    partial_ratio: float = 0.55,
    exclude_days=None,
):
    """Combine zero-row gaps and partial-volume days needing refetch."""
    missing_report = detect_missing_fetch_days(
        db, start_date, end_date, min_neighbor_rows=min_neighbor_rows,
    )
    refetch = {m['day']: m for m in (missing_report.get('missing_days') or [])}

    partial_report = {'partial_days': []}
    if detect_partial:
        partial_report = detect_partial_fetch_days(
            db,
            start_date,
            end_date,
            min_rows=partial_min_rows,
            ratio=partial_ratio,
            exclude_days=exclude_days,
        )
        for p in partial_report.get('partial_days') or []:
            day = p['day']
            if day not in refetch:
                refetch[day] = p

    daily = missing_report.get('daily') or []
    for row in daily:
        fetched = int(row.get('fetched_total') or 0)
        pending = int(row.get('pending_analysis') or 0)
        analyzed = int(row.get('source_analyzed') or 0)
        if fetched < 1:
            stage = 'not_fetched'
        elif row['day'] in refetch:
            stage = 'partial_fetch'
        elif pending > 0:
            stage = 'partial_analysis'
        elif analyzed > 0:
            stage = 'analyzed'
        else:
            stage = 'fetched'
        row['pipeline_stage'] = stage
        row['analysis_pct'] = round(100.0 * analyzed / fetched, 1) if fetched else 0.0

    refetch_days = sorted(refetch.values(), key=lambda x: x['day'])
    return {
        **missing_report,
        'partial_days': partial_report.get('partial_days') or [],
        'refetch_days': refetch_days,
        'refetch_day_list': [d['day'] for d in refetch_days],
        'daily': daily,
    }


def detect_sparse_days(
    db: Database,
    start_date: str,
    end_date: str,
    *,
    min_rows: int = 1000,
    min_affiliates: int = 50,
    row_ratio: float = 0.15,
    affiliate_ratio: float = 0.25,
):
    """
    Compare each day to median of neighbors in range.
    Returns list of anomaly dicts sorted by severity.
    """
    rows = db.get_daily_free_coverage(start_date, end_date)
    by_day = {str(r['day']): r for r in rows}

    start = _parse_day(start_date)
    end = _parse_day(end_date)
    all_days = list(_iter_days(start, end))

    counts = [int(by_day[d]['row_count']) for d in all_days if d in by_day]
    affs = [int(by_day[d]['affiliate_count']) for d in all_days if d in by_day]
    if not counts:
        return {'sparse_days': [], 'summary': {}, 'daily': []}

    median_rows = sorted(counts)[len(counts) // 2] if counts else 0
    median_aff = sorted(affs)[len(affs) // 2] if affs else 0

    sparse = []
    daily_out = []
    for day in all_days:
        r = by_day.get(day)
        if not r:
            daily_out.append({
                'day': day,
                'row_count': 0,
                'affiliate_count': 0,
                'analyzed_count': 0,
                'missing': True,
            })
            sparse.append({
                'day': day,
                'reason': 'no_rows',
                'row_count': 0,
                'affiliate_count': 0,
                'median_rows': median_rows,
                'median_affiliates': median_aff,
            })
            continue

        rc = int(r['row_count'] or 0)
        ac = int(r['affiliate_count'] or 0)
        daily_out.append({
            'day': day,
            'row_count': rc,
            'affiliate_count': ac,
            'analyzed_count': int(r.get('analyzed_count') or 0),
            'min_duid': r.get('min_duid'),
            'max_duid': r.get('max_duid'),
            'missing': False,
        })

        reasons = []
        if rc < min_rows:
            reasons.append(f'rows<{min_rows}')
        if ac < min_affiliates:
            reasons.append(f'affiliates<{min_affiliates}')
        if median_rows and rc < median_rows * row_ratio:
            reasons.append(f'rows<{row_ratio:.0%}_of_median')
        if median_aff and ac < median_aff * affiliate_ratio:
            reasons.append(f'affiliates<{affiliate_ratio:.0%}_of_median')

        if reasons:
            sparse.append({
                'day': day,
                'reason': ','.join(reasons),
                'row_count': rc,
                'affiliate_count': ac,
                'analyzed_count': int(r.get('analyzed_count') or 0),
                'median_rows': median_rows,
                'median_affiliates': median_aff,
            })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'median_daily_rows': median_rows,
        'median_daily_affiliates': median_aff,
        'sparse_days': sparse,
        'daily': daily_out,
    }


def affiliate_coverage(db: Database, affiliate: str, start_date: str, end_date: str):
    import sqlite3

    aff = affiliate.strip().lower()
    with db.get_connection() as conn:
        cur = conn.execute(
            """
            SELECT date(trans_datetime) AS day,
                   COUNT(*) AS row_count,
                   SUM(CASE WHEN analyzed THEN 1 ELSE 0 END) AS analyzed_count
            FROM free
            WHERE lower(COALESCE(NULLIF(webmaster_code, ''), site_code, '')) = ?
              AND date(trans_datetime) BETWEEN date(?) AND date(?)
            GROUP BY date(trans_datetime)
            ORDER BY day
            """,
            (aff, start_date, end_date),
        )
        rows = [
            {'day': r[0], 'row_count': r[1], 'analyzed_count': r[2]}
            for r in cur.fetchall()
        ]
        total = conn.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN analyzed THEN 1 ELSE 0 END)
            FROM free
            WHERE lower(COALESCE(NULLIF(webmaster_code, ''), site_code, '')) = ?
              AND date(trans_datetime) BETWEEN date(?) AND date(?)
            """,
            (aff, start_date, end_date),
        ).fetchone()
    return {
        'affiliate': affiliate,
        'start_date': start_date,
        'end_date': end_date,
        'total_rows': int(total[0] or 0),
        'total_analyzed': int(total[1] or 0),
        'daily': rows,
    }


def main():
    parser = argparse.ArgumentParser(description='Audit daily free-table coverage')
    parser.add_argument('--db', default=str(ROOT / 'affiliate_data.db'))
    parser.add_argument('--start', default=None, help='YYYY-MM-DD (default: 30 days ago)')
    parser.add_argument('--end', default=None, help='YYYY-MM-DD (default: today)')
    parser.add_argument('--affiliate', default=None, help='Optional affiliate drill-down')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    end = args.end or datetime.now().strftime('%Y-%m-%d')
    start = args.start or (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    db = Database(args.db)
    db.setup_database()

    report = detect_sparse_days(db, start, end)
    if args.affiliate:
        report['affiliate_detail'] = affiliate_coverage(db, args.affiliate, start, end)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return

    print(f"Coverage audit {start} → {end}")
    print(f"Median daily free rows: {report.get('median_daily_rows', 0):,}")
    print(f"Median daily affiliates: {report.get('median_daily_affiliates', 0):,}")
    print()
    sparse = report.get('sparse_days') or []
    if not sparse:
        print('No sparse days detected.')
    else:
        print(f'Sparse / missing days ({len(sparse)}):')
        for s in sparse:
            print(
                f"  {s['day']}: rows={s.get('row_count', 0):,} "
                f"affiliates={s.get('affiliate_count', 0):,} "
                f"reason={s.get('reason')}"
            )

    if args.affiliate:
        ad = report.get('affiliate_detail') or {}
        print()
        print(
            f"Affiliate {args.affiliate}: "
            f"{ad.get('total_rows', 0)} raw rows, "
            f"{ad.get('total_analyzed', 0)} analyzed in range"
        )
        for d in ad.get('daily') or []:
            print(
                f"  {d['day']}: rows={d['row_count']} analyzed={d['analyzed_count']}"
            )


if __name__ == '__main__':
    main()
