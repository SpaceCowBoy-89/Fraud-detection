"""Flask routes for per-user admin2 session login."""

import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret-for-admin2-sessions')
    monkeypatch.setenv('ADMIN2_LOGIN_REQUIRED', '1')
    monkeypatch.setenv('SKIP_EMBEDDED_SCHEDULER', '1')
    db_path = tmp_path / 'test.db'
    from database import Database
    from config import Config
    from dashboard.app import create_app

    cfg = Config(str(tmp_path / 'config.json'))
    db = Database(str(db_path))
    app = create_app(db, cfg, api_client=None)
    app.config['TESTING'] = True
    return app.test_client()


def test_admin2_status_not_authenticated(app_client):
    rv = app_client.get('/api/auth/admin2/status')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['authenticated'] is False
    assert data['login_required'] is True


def test_admin2_login_success(app_client, monkeypatch):
    class FakeClient:
        def test_connection(self):
            return True, 'ok'

    monkeypatch.setattr('dashboard.app.AdminAPIClient', lambda u, p: FakeClient())

    rv = app_client.post(
        '/api/auth/admin2/login',
        json={'username': 'alice', 'password': 'secret'},
    )
    assert rv.status_code == 200
    assert rv.get_json()['ok'] is True

    st = app_client.get('/api/auth/admin2/status').get_json()
    assert st['authenticated'] is True
    assert 'ali' in st['username_preview']


def test_api_blocked_without_admin2_session(app_client):
    rv = app_client.get('/api/stats')
    assert rv.status_code == 401
    assert rv.get_json().get('code') == 'admin2_auth_required'


def test_admin2_login_bad_credentials(app_client, monkeypatch):
    class FakeClient:
        def test_connection(self):
            return False, 'Authentication failed'

    monkeypatch.setattr('dashboard.app.AdminAPIClient', lambda u, p: FakeClient())

    rv = app_client.post(
        '/api/auth/admin2/login',
        json={'username': 'alice', 'password': 'wrong'},
    )
    assert rv.status_code == 401
