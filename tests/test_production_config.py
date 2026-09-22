"""Production config guards and sanitized API errors."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_require_flask_secret_fails_when_enforced(monkeypatch):
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    monkeypatch.setenv('REQUIRE_FLASK_SECRET_KEY', '1')
    monkeypatch.delenv('DEBUG', raising=False)
    from dashboard.production_config import require_flask_secret

    with pytest.raises(RuntimeError, match='FLASK_SECRET_KEY'):
        require_flask_secret(testing=False)


def test_require_flask_secret_ok_when_set(monkeypatch):
    monkeypatch.setenv('FLASK_SECRET_KEY', 'abc123')
    monkeypatch.setenv('REQUIRE_FLASK_SECRET_KEY', '1')
    from dashboard.production_config import require_flask_secret

    assert require_flask_secret(testing=False) == 'abc123'


def test_require_flask_secret_skipped_in_testing(monkeypatch):
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    monkeypatch.setenv('REQUIRE_FLASK_SECRET_KEY', '1')
    from dashboard.production_config import require_flask_secret

    assert require_flask_secret(testing=True) == ''


def test_session_cookie_defaults(monkeypatch):
    monkeypatch.delenv('SESSION_COOKIE_SECURE', raising=False)
    monkeypatch.delenv('TRUST_PROXY_HTTPS', raising=False)
    from dashboard.production_config import session_cookie_settings

    s = session_cookie_settings()
    assert s['SESSION_COOKIE_HTTPONLY'] is True
    assert s['SESSION_COOKIE_SECURE'] is False
    assert s['SESSION_COOKIE_SAMESITE'] == 'Lax'


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv('SKIP_EMBEDDED_SCHEDULER', '1')
    monkeypatch.setenv('LOG_TO_STDOUT_ONLY', '1')
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret-api-errors')
    monkeypatch.setenv('ADMIN2_LOGIN_REQUIRED', '0')
    monkeypatch.delenv('DEBUG', raising=False)

    from logging_config import reset_logging_config, configure_logging

    reset_logging_config()
    configure_logging('test-api-errors')

    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text('{}', encoding='utf-8')
    db_path = tmp_path / 'test_app.db'

    from run import build_app

    application = build_app(config_path=str(cfg_path), database_path=str(db_path))
    application.config['TESTING'] = True
    application.config['DEBUG'] = False

    @application.route('/api/_test/boom')
    def _boom():
        raise RuntimeError('secret stack path /tmp/leak')

    return application.test_client()


def test_unhandled_500_hides_details_outside_debug(app_client, monkeypatch):
    # Force non-debug exposure even under TESTING for this assertion
    monkeypatch.setenv('DEBUG', '0')
    from dashboard import api_errors

    monkeypatch.setattr(api_errors, '_expose_details', lambda: False)

    rv = app_client.get('/api/_test/boom')
    assert rv.status_code == 500
    data = rv.get_json()
    assert data['error'] == 'Internal server error'
    assert 'details' not in data
    assert 'leak' not in str(data)


def test_http_404_not_folded_into_500(app_client):
    rv = app_client.get('/api/this-route-does-not-exist-xyz')
    assert rv.status_code == 404
