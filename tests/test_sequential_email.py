"""Tests for per-affiliate sequential email (stem + numeric suffix) detection."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database
from scripts.email_fraud_detector import (
    EmailFraudDetector,
    normalize_duid_join_key,
    rescore_sequential_email_from_fraud_results_table,
)


def _norm_and_build(detector, df):
    detector.normalize_column_names(df)
    detector.build_sequential_email_map(df)


def test_normalize_duid_join_key_float_vs_string():
    assert normalize_duid_join_key('384046981') == normalize_duid_join_key(384046981.0) == '384046981'


def test_rescore_joins_when_duid_formats_differ(tmp_path):
    """fraud_results DUID as string, free DUID as numeric-looking string — still resolves email."""
    dbp = str(tmp_path / 'seq_duid.db')
    db = Database(dbp)
    with sqlite3.connect(dbp) as conn:
        for i in range(1, 5):
            conn.execute(
                """INSERT INTO free (duid, email, site_code, user1, trans_datetime)
                   VALUES (?, ?, 'affx', 'MAN', '2025-01-01')""",
                (384046980 + i, f'acct{i}@z.com'),
            )
        for i in range(1, 5):
            conn.execute(
                """INSERT INTO fraud_results (
                       duid, email, risk_score, flags, details, data_type,
                       webmaster_code, custom_u1
                   ) VALUES (?, NULL, 1, '[]', '{}', 'free', NULL, NULL)""",
                (str(384046980 + i),),
            )
        conn.commit()

    out = rescore_sequential_email_from_fraud_results_table(db)
    assert out['rows_considered'] == 4
    assert out['updated'] == 4


def test_build_sequential_email_map_triggers_at_four():
    detector = EmailFraudDetector()
    df = pd.DataFrame(
        {
            'email': [
                'maucheesee71@mail.com',
                'maucheesee76@mail.com',
                'maucheesee79@mail.com',
                'maucheesee81@mail.com',
            ],
            'webmaster_code': ['lukutoy25'] * 4,
        }
    )
    _norm_and_build(detector, df)
    key = ('lukutoy25', 'maucheesee', 'mail.com')
    assert key in detector.sequential_email_flags
    assert detector.sequential_email_flags[key]['count'] == 4


def test_build_sequential_email_map_not_triggered_with_three():
    detector = EmailFraudDetector()
    df = pd.DataFrame(
        {
            'email': [
                'foobar10@x.com',
                'foobar11@x.com',
                'foobar12@x.com',
            ],
            'webmaster_code': ['aff'] * 3,
        }
    )
    _norm_and_build(detector, df)
    assert not detector.sequential_email_flags


def test_build_sequential_email_map_no_cross_affiliate():
    detector = EmailFraudDetector()
    df = pd.DataFrame(
        {
            'email': [
                'stem1@d.com',
                'stem2@d.com',
                'stem3@d.com',
                'stem4@d.com',
                'stem5@d.com',
                'stem6@d.com',
                'stem7@d.com',
                'stem8@d.com',
            ],
            'webmaster_code': ['A', 'A', 'A', 'A', 'B', 'B', 'B', 'B'],
        }
    )
    _norm_and_build(detector, df)
    assert ('A', 'stem', 'd.com') in detector.sequential_email_flags
    assert ('B', 'stem', 'd.com') in detector.sequential_email_flags
    assert len(detector.sequential_email_flags) == 2


def test_apply_sequential_email_idempotent():
    detector = EmailFraudDetector()
    df = pd.DataFrame(
        {
            'email': [f'acct{i}@z.com' for i in range(1, 5)],
            'webmaster_code': ['aff'] * 4,
        }
    )
    _norm_and_build(detector, df)
    results = [
        {
            'email': f'acct{i}@z.com',
            'webmaster_code': 'aff',
            'risk_score': 5,
            'flags': [],
            'details': {},
        }
        for i in range(1, 5)
    ]
    detector.apply_sequential_email_to_results(results)
    rs1 = results[0]['risk_score']
    detector.apply_sequential_email_to_results(results)
    assert results[0]['risk_score'] == rs1
    assert results[0]['flags'].count('SEQUENTIAL_EMAIL') == 1


def test_rescore_sequential_email_integration(tmp_path):
    dbp = str(tmp_path / 'seq.db')
    db = Database(dbp)
    with sqlite3.connect(dbp) as conn:
        for i in range(1, 5):
            conn.execute(
                """INSERT INTO fraud_results (
                       duid, email, risk_score, flags, details, data_type,
                       webmaster_code, custom_u1
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(200000 + i),
                    f'acct{i}@z.com',
                    3,
                    '[]',
                    '{}',
                    'free',
                    'aff1',
                    'MAN',
                ),
            )
        conn.commit()

    out1 = rescore_sequential_email_from_fraud_results_table(db)
    assert out1['updated'] == 4
    assert out1['clusters_found'] >= 1

    out2 = rescore_sequential_email_from_fraud_results_table(db)
    assert out2['updated'] == 0

    with sqlite3.connect(dbp) as conn:
        row = conn.execute(
            "SELECT flags FROM fraud_results WHERE duid = ?", ('200001',)
        ).fetchone()
    assert row and 'SEQUENTIAL_EMAIL' in row[0]


def test_rescore_sequential_email_backfills_email_from_source(tmp_path):
    """When fraud_results.email is empty, rescore still sees email from free."""
    dbp = str(tmp_path / 'seq_bf.db')
    db = Database(dbp)
    with sqlite3.connect(dbp) as conn:
        for i in range(1, 5):
            duid = str(300000 + i)
            conn.execute(
                """INSERT INTO free (duid, email, site_code, user1, trans_datetime)
                   VALUES (?, ?, 'affbf', 'MAN', '2025-01-01')""",
                (duid, f'acct{i}@z.com'),
            )
            conn.execute(
                """INSERT INTO fraud_results (
                       duid, email, risk_score, flags, details, data_type,
                       webmaster_code, custom_u1
                   ) VALUES (?, NULL, 2, '[]', '{}', 'free', NULL, NULL)""",
                (duid,),
            )
        conn.commit()

    out = rescore_sequential_email_from_fraud_results_table(db)
    assert out['rows_considered'] == 4
    assert out['updated'] == 4
    assert out['clusters_found'] >= 1
