"""Review queue / fraud-results metadata and job lock coordination."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def db(tmp_path):
    from database import Database

    return Database(str(tmp_path / 'locks.db'))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv('SKIP_EMBEDDED_SCHEDULER', '1')
    monkeypatch.setenv('LOG_TO_STDOUT_ONLY', '1')
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret-review-api')
    monkeypatch.setenv('ADMIN2_LOGIN_REQUIRED', '0')

    from logging_config import reset_logging_config, configure_logging

    reset_logging_config()
    configure_logging('test-review-api')

    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text('{}', encoding='utf-8')
    db_path = tmp_path / 'review.db'

    from database import Database
    from run import build_app

    db = Database(str(db_path))
    # Seed a few unreviewed high-risk rows
    with db.get_connection() as conn:
        for i in range(5):
            conn.execute(
                '''INSERT INTO fraud_results
                   (duid, email, risk_score, flags, payout_amount, data_type, analyzed_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))''',
                (f'duid-{i}', f'user{i}@example.com', 60 + i, '["SCRAMBLED_PATTERN"]', 10.0, 'free'),
            )

    application = build_app(config_path=str(cfg_path), database_path=str(db_path))
    application.config['TESTING'] = True
    return application.test_client()


def test_pending_reviews_returns_metadata(app_client):
    rv = app_client.get('/api/pending-reviews?limit=2')
    assert rv.status_code == 200
    data = rv.get_json()
    assert 'records' in data
    assert data['total'] == 5
    assert data['limit'] == 2
    assert data['truncated'] is True
    assert len(data['records']) == 2


def test_fraud_results_returns_metadata(app_client):
    rv = app_client.get('/api/fraud-results?min_risk=50&limit=2')
    assert rv.status_code == 200
    data = rv.get_json()
    assert 'records' in data
    assert data['total'] >= 5
    assert data['limit'] == 2
    assert data['truncated'] is True


def test_named_lock_acquire_and_contention(db):
    assert db.try_acquire_named_lock('pipeline', 'holder-a', stale_hours=12) is True
    assert db.try_acquire_named_lock('pipeline', 'holder-b', stale_hours=12) is False
    db.release_named_lock('pipeline', 'holder-a')
    assert db.try_acquire_named_lock('pipeline', 'holder-b', stale_hours=12) is True


def test_named_lock_stale_takeover(db):
    assert db.try_acquire_named_lock('pipeline', 'old', stale_hours=12) is True
    # Backdate the lock
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE job_locks SET acquired_at = datetime('now', '-48 hours') WHERE name = 'pipeline'"
        )
    assert db.try_acquire_named_lock('pipeline', 'new', stale_hours=12) is True
    db.release_named_lock('pipeline', 'new')


def test_count_pending_reviews(db):
    with db.get_connection() as conn:
        conn.execute(
            '''INSERT INTO fraud_results
               (duid, email, risk_score, flags, payout_amount, data_type, analyzed_at)
               VALUES ('x1', 'a@b.com', 80, '[]', 1, 'free', datetime('now'))'''
        )
    assert db.count_pending_reviews(min_risk=50) == 1
    assert db.count_fraud_results(min_risk=50, exclude_reviewed=True) == 1
