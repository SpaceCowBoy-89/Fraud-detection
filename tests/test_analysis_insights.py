"""Tests for analysis insights and shared flag utilities."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from database import Database  # noqa: E402
from flag_utils import (  # noqa: E402
    catalog_flags_from_cell,
    precision_confidence,
    rule_status,
)
from analysis_insights import AnalysisInsights  # noqa: E402


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = Database(path)
    yield db
    os.unlink(path)


@pytest.fixture
def insights_db(temp_db):
    """Populate fraud_results and outcomes for insight tests."""
    now = datetime.now()
    recent = (now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    old = (now - timedelta(days=20)).strftime('%Y-%m-%d %H:%M:%S')

    rows = [
        # Recent high-risk with sequential + name patterns
        ('d1', 'a1@test.com', "['SEQUENTIAL_EMAIL', 'NAME_NUMBER_PATTERN']", 65, 100.0, 'AFF1', 'C1', recent, 'confirmed_fraud'),
        ('d2', 'a2@test.com', "['SEQUENTIAL_EMAIL']", 55, 80.0, 'AFF1', 'C1', recent, 'false_positive'),
        ('d3', 'a3@evil.com', "['NAME_NUMBER_PATTERN']", 60, 90.0, 'AFF2', 'C2', recent, 'confirmed_fraud'),
        # Older baseline
        ('d4', 'b1@test.com', "['SEQUENTIAL_EMAIL']", 52, 70.0, 'AFF1', 'C1', old, None),
        ('d5', 'b2@test.com', "['DIGIT_SUFFIX']", 30, 40.0, 'AFF2', 'C2', old, None),
        # Unreviewed high risk
        ('d6', 'c1@new.com', "['SEQUENTIAL_EMAIL', 'DIGIT_SUFFIX']", 72, 120.0, 'AFF3', 'C3', recent, None),
    ]

    with temp_db.get_connection() as conn:
        for duid, email, flags, risk, payout, aff, camp, dt, outcome in rows:
            conn.execute("""
                INSERT INTO fraud_results
                (duid, email, flags, risk_score, payout_amount, webmaster_code, campaign, analyzed_at, trans_datetime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (duid, email, flags, risk, payout, aff, camp, dt, dt))
            if outcome:
                conn.execute("""
                    INSERT INTO fraud_outcomes (duid, email, outcome, risk_score, payout_amount, flags, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (duid, email, outcome, risk, payout, flags, dt))

    return temp_db


def test_precision_confidence_labels():
    assert precision_confidence(50) == 'strong'
    assert precision_confidence(15) == 'directional'
    assert precision_confidence(5) == 'too_little_data'


def test_rule_status_thresholds():
    assert rule_status(85, 40) == 'good'
    assert rule_status(45, 20) == 'caution'
    assert rule_status(70, 5) == 'neutral'


def test_catalog_flags_from_cell():
    cell = "['geo_login_mismatch_US_CA', 'SEQUENTIAL_EMAIL']"
    keys = catalog_flags_from_cell(cell)
    assert 'geo_login_mismatch' in keys
    assert 'SEQUENTIAL_EMAIL' in keys


def test_compute_rule_stats(insights_db):
    ai = AnalysisInsights(insights_db)
    data = ai.compute_rule_stats()
    rules = {r['rule']: r for r in data['rules']}
    assert 'SEQUENTIAL_EMAIL' in rules
    seq = rules['SEQUENTIAL_EMAIL']
    assert seq['flagged'] >= 3
    assert seq['reviewed'] >= 2
    assert seq['confidence'] in ('strong', 'directional', 'too_little_data')
    assert 'unreviewed' in seq


def test_compute_fp_analysis(insights_db):
    ai = AnalysisInsights(insights_db)
    data = ai.compute_fp_analysis()
    assert data['total_reviewed'] >= 3
    assert data['total_fraud'] >= 2


def test_compute_rising_patterns(insights_db):
    ai = AnalysisInsights(insights_db)
    data = ai.compute_rising_patterns(recent_days=7, baseline_days=28, min_recent=2, min_delta_pct=0)
    assert 'flags' in data
    assert 'domains' in data
    assert data['window']['recent_days'] == 7


def test_compute_rule_cooccurrence(insights_db):
    ai = AnalysisInsights(insights_db)
    data = ai.compute_rule_cooccurrence(min_reviewed=1)
    assert 'pairs' in data
    combo_text = ' '.join(p['combo'] for p in data['pairs'])
    assert 'SEQUENTIAL_EMAIL' in combo_text or 'NAME_NUMBER_PATTERN' in combo_text


def test_compute_review_coverage(insights_db):
    ai = AnalysisInsights(insights_db)
    data = ai.compute_review_coverage()
    assert data['tiers']['high']['total'] >= 3
    assert 'pct_reviewed' in data['tiers']['high']
    assert 'sampling' in data


def test_compute_action_items(insights_db):
    ai = AnalysisInsights(insights_db)
    data = ai.compute_action_items()
    assert 'items' in data
    assert isinstance(data['items'], list)


def test_record_low_risk_sample_review(insights_db):
    temp_db = insights_db
    with temp_db.get_connection() as conn:
        conn.execute("""
            INSERT INTO fraud_results
            (duid, email, flags, risk_score, payout_amount, webmaster_code, analyzed_at)
            VALUES ('low99', 'low@test.com', "['DIGIT_SUFFIX']", 12, 25.0, 'AFFX', datetime('now'))
        """)
    temp_db.sample_low_risk_accounts(count=1, max_risk=24)
    samples = temp_db.get_low_risk_samples(status='pending')
    assert not samples.empty
    duid = samples.iloc[0]['duid']
    assert temp_db.record_low_risk_review(duid, 'missed_fraud', 'test')
    updated = temp_db.get_low_risk_samples(status='missed_fraud')
    assert duid in updated['duid'].values


def test_analysis_api_endpoints(tmp_path, monkeypatch):
    """Smoke test new /api/analysis/* routes."""
    monkeypatch.setenv('SKIP_EMBEDDED_SCHEDULER', '1')
    monkeypatch.setenv('LOG_TO_STDOUT_ONLY', '1')
    monkeypatch.setenv('ADMIN2_LOGIN_REQUIRED', '0')
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret-analysis-api')

    from logging_config import reset_logging_config, configure_logging
    reset_logging_config()
    configure_logging('test-analysis-api')

    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text('{}', encoding='utf-8')
    db_path = tmp_path / 'test_app.db'

    from run import build_app
    application = build_app(config_path=str(cfg_path), database_path=str(db_path))
    application.config['TESTING'] = True
    client = application.test_client()

    for path in (
        '/api/analysis/action-items',
        '/api/analysis/rising-patterns',
        '/api/analysis/rule-cooccurrence',
        '/api/analysis/review-coverage',
        '/api/rule-performance',
    ):
        rv = client.get(path)
        assert rv.status_code == 200, path

    body = client.get('/api/rule-performance').get_json()
    assert 'rules' in body
    assert 'summary' in body
