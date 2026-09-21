"""Flag reference export is available without admin2 session."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIP_EMBEDDED_SCHEDULER", "1")
    monkeypatch.setenv("LOG_TO_STDOUT_ONLY", "1")
    monkeypatch.setenv("ADMIN2_LOGIN_REQUIRED", "1")

    from logging_config import reset_logging_config, configure_logging

    reset_logging_config()
    configure_logging("test-flag-ref-export")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    db_path = tmp_path / "test_app.db"

    from run import build_app

    application = build_app(
        config_path=str(cfg_path),
        database_path=str(db_path),
    )
    application.config["TESTING"] = True
    return application.test_client()


def test_flag_reference_csv_without_admin_session(app_client):
    r = app_client.get("/api/export/flag-reference?format=csv")
    assert r.status_code == 200
    assert "text/csv" in (r.content_type or "")
    body = r.data.decode("utf-8-sig")
    assert "catalog_key" in body
    assert "AFFILIATE_DOMAIN_CONCENTRATION" in body


def test_flag_reference_md_without_admin_session(app_client):
    r = app_client.get("/api/export/flag-reference?format=md")
    assert r.status_code == 200
    assert "Fraud detection flags" in r.data.decode("utf-8")
