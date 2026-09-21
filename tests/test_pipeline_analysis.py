"""Tests for shared pipeline analysis drain helpers."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from unittest.mock import MagicMock

from database import Database
from pipeline_analysis import drain_unanalyzed_for_day, iter_days_in_range


def test_iter_days_in_range():
    days = list(iter_days_in_range('2026-07-01', '2026-07-03'))
    assert days == ['2026-07-01', '2026-07-02', '2026-07-03']


def test_drain_unanalyzed_for_day_marks_rows(tmp_path, monkeypatch):
    dbp = str(tmp_path / 'drain.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        for i in range(5):
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, analyzed)
                   VALUES (?, ?, ?, 0)""",
                (f'900{i}', f'user{i}@example.com', '2026-07-03 12:00:00'),
            )
        conn.commit()

    config = MagicMock()
    config.get.side_effect = lambda k, default=None: {'min_duid_threshold': 0}.get(k, default)

    def fake_analyze(_db, _config, data_type, df, **kwargs):
        duids = [str(r['duid']) for _, r in df.iterrows()]
        if duids:
            _db.mark_as_analyzed(duids, data_type)
        return {'analyzed': len(duids), 'high_risk': 0}

    import pipeline_analysis as pa
    monkeypatch.setattr(pa, 'analyze_dataframe', fake_analyze)

    summary = pa.drain_unanalyzed_for_day(
        db, config, '2026-07-03', batch_limit=500, max_batches=5,
    )
    assert summary['analyzed'] == 5
    assert summary['complete'] is True
    assert db.count_unanalyzed_for_day('2026-07-03') == 0


def test_get_priority_unanalyzed_day_recent(tmp_path):
    dbp = str(tmp_path / 'prio.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        conn.execute(
            """INSERT INTO free (duid, email, trans_datetime, analyzed)
               VALUES ('1', 'a@x.com', '2026-07-01 12:00:00', 0)"""
        )
        conn.execute(
            """INSERT INTO free (duid, email, trans_datetime, analyzed)
               VALUES ('2', 'b@x.com', '2026-07-05 12:00:00', 0)"""
        )
        conn.commit()

    assert db.get_priority_unanalyzed_day(lookback_days=14, priority='recent') == '2026-07-05'
    assert db.get_priority_unanalyzed_day(lookback_days=14, priority='oldest') == '2026-07-01'


def test_analyze_dataframe_marks_skipped_house_rows(tmp_path, monkeypatch):
    dbp = str(tmp_path / 'skip.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        conn.execute(
            """INSERT INTO free (duid, email, webmaster_code, trans_datetime, analyzed)
               VALUES ('9001', 'a@x.com', 'rkhouse', '2026-07-09 12:00:00', 0)"""
        )
        conn.commit()

    import pandas as pd
    import pipeline_analysis as pa

    config = MagicMock()
    config.get.return_value = 0
    config.get_risk_threshold.return_value = 50
    config.get_affiliate_analysis_skip_codes_lower.return_value = {'rkhouse'}

    summary = pa.analyze_dataframe(
        db,
        config,
        'free',
        pd.read_sql_query('SELECT * FROM free', sqlite3.connect(dbp)),
        min_duid=0,
    )
    assert summary['analyzed'] == 0
    assert summary['skipped'] == 1
    assert db.count_unanalyzed_for_day('2026-07-09') == 0
