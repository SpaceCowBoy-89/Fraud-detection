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
    from datetime import datetime, timedelta

    dbp = str(tmp_path / 'prio.db')
    db = Database(dbp)
    db.setup_database()

    older = (datetime.utcnow().date() - timedelta(days=5)).strftime('%Y-%m-%d')
    newer = (datetime.utcnow().date() - timedelta(days=1)).strftime('%Y-%m-%d')

    with sqlite3.connect(dbp) as conn:
        conn.execute(
            """INSERT INTO free (duid, email, trans_datetime, analyzed)
               VALUES ('1', 'a@x.com', ?, 0)""",
            (f'{older} 12:00:00',),
        )
        conn.execute(
            """INSERT INTO free (duid, email, trans_datetime, analyzed)
               VALUES ('2', 'b@x.com', ?, 0)""",
            (f'{newer} 12:00:00',),
        )
        conn.commit()

    assert db.get_priority_unanalyzed_day(lookback_days=14, priority='recent') == newer
    assert db.get_priority_unanalyzed_day(lookback_days=14, priority='oldest') == older


def test_analyze_dataframe_marks_skipped_house_rows(tmp_path):
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

    class _Cfg:
        def get(self, key, default=None):
            if key == 'min_duid_threshold':
                return 0
            if key == 'risk_scores':
                return {}
            return default

        def get_risk_threshold(self, level):
            return 50 if level == 'high' else 25

        def get_affiliate_analysis_skip_codes_lower(self, include_house_in_analysis=False):
            return {'rkhouse'}

    summary = pa.analyze_dataframe(
        db,
        _Cfg(),
        'free',
        pd.read_sql_query('SELECT * FROM free', sqlite3.connect(dbp)),
        min_duid=0,
    )
    assert summary['analyzed'] == 0
    assert summary['skipped'] == 1
    assert db.count_unanalyzed_for_day('2026-07-09') == 0


def test_analyze_dataframe_writes_enrichment_fields(tmp_path):
    """geo/ip/custom_u1 should be on fraud_results at insert — no save-time backfill needed."""
    dbp = str(tmp_path / 'enrich.db')
    db = Database(dbp)
    db.setup_database()

    with sqlite3.connect(dbp) as conn:
        conn.execute(
            """INSERT INTO free (duid, email, webmaster_code, trans_datetime, analyzed,
                                 ip, geo_country, user1)
               VALUES ('9101', 'legit.user@gmail.com', 'aff1', '2026-07-10 12:00:00', 0,
                       '1.2.3.4', 'US', 'MAN')"""
        )
        conn.commit()

    import pandas as pd
    import pipeline_analysis as pa

    class _Cfg:
        def get(self, key, default=None):
            if key == 'min_duid_threshold':
                return 0
            if key == 'risk_scores':
                return {}
            return default

        def get_risk_threshold(self, level):
            return 50 if level == 'high' else 25

        def get_affiliate_analysis_skip_codes_lower(self, include_house_in_analysis=False):
            return set()

    summary = pa.analyze_dataframe(
        db,
        _Cfg(),
        'free',
        pd.read_sql_query('SELECT * FROM free', sqlite3.connect(dbp)),
        min_duid=0,
    )
    assert summary['analyzed'] == 1

    with sqlite3.connect(dbp) as conn:
        row = conn.execute(
            "SELECT ip, geo_country, custom_u1 FROM fraud_results WHERE duid = '9101'"
        ).fetchone()
    assert row is not None
    assert row[0] == '1.2.3.4'
    assert row[1] == 'US'
    assert row[2] == 'MAN'