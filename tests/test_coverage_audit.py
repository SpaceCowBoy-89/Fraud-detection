"""Tests for daily coverage audit."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database
from scripts.coverage_audit import (
    detect_coverage_gaps,
    detect_missing_fetch_days,
    detect_partial_fetch_days,
    detect_sparse_days,
)


def test_detect_sparse_days_flags_missing_and_low_volume(tmp_path):
    dbp = str(tmp_path / 'cov.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        # Normal day
        for i in range(100):
            conn.execute(
                """INSERT INTO free (duid, email, site_code, trans_datetime, analyzed)
                   VALUES (?, ?, ?, ?, 0)""",
                (f'100{i:03d}', f'u{i}@x.com', f'aff{i % 20}', '2026-06-10 12:00:00',),
            )
        # Sparse day — one affiliate only
        for i in range(5):
            conn.execute(
                """INSERT INTO free (duid, email, site_code, trans_datetime, analyzed)
                   VALUES (?, ?, ?, ?, 0)""",
                (f'200{i}', f's{i}@x.com', 'onlyaff', '2026-06-11 12:00:00',),
            )
        conn.commit()

    report = detect_sparse_days(db, '2026-06-10', '2026-06-12', min_rows=50, min_affiliates=10)
    sparse_days = {s['day'] for s in report['sparse_days']}
    assert '2026-06-11' in sparse_days
    assert '2026-06-12' in sparse_days  # missing entirely


def test_detect_partial_fetch_days_flags_low_volume(tmp_path):
    dbp = str(tmp_path / 'partial.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        for i in range(1200):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'1{i:04d}', f'a{i}@x.com', '2026-07-02 12:00:00'),
            )
        for i in range(600):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'2{i:04d}', f'b{i}@x.com', '2026-07-03 12:00:00'),
            )
        for i in range(1200):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'3{i:04d}', f'c{i}@x.com', '2026-07-05 12:00:00'),
            )
        conn.commit()

    report = detect_partial_fetch_days(
        db, '2026-07-01', '2026-07-06', min_rows=500, ratio=0.55,
    )
    partial = {p['day'] for p in report['partial_days']}
    assert '2026-07-03' in partial
    assert '2026-07-02' not in partial


def test_detect_coverage_gaps_adds_pipeline_stage(tmp_path):
    dbp = str(tmp_path / 'gaps.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        for i in range(1200):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 1)""",
                (f'1{i:04d}', f'a{i}@x.com', '2026-07-02 12:00:00'),
            )
        for i in range(1200):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'2{i:04d}', f'b{i}@x.com', '2026-07-05 12:00:00'),
            )
        conn.commit()

    report = detect_coverage_gaps(
        db, '2026-07-01', '2026-07-06',
        min_neighbor_rows=1000,
        partial_min_rows=500,
    )
    by_day = {d['day']: d for d in report['daily']}
    assert by_day['2026-07-03']['pipeline_stage'] == 'not_fetched'
    assert by_day['2026-07-05']['pipeline_stage'] == 'partial_analysis'


def test_detect_missing_fetch_days_flags_zero_gap(tmp_path):
    dbp = str(tmp_path / 'gap.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        for i in range(1200):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'1{i:04d}', f'a{i}@x.com', '2026-07-02 12:00:00'),
            )
        for i in range(1300):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'2{i:04d}', f'b{i}@x.com', '2026-07-05 12:00:00'),
            )
        conn.commit()

    report = detect_missing_fetch_days(
        db, '2026-07-01', '2026-07-06', min_neighbor_rows=1000,
    )
    missing = {m['day'] for m in report['missing_days']}
    assert '2026-07-03' in missing
    assert '2026-07-04' in missing
    assert '2026-07-02' not in missing
