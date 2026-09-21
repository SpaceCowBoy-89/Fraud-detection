"""Health / readiness endpoints for the Flask dashboard."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIP_EMBEDDED_SCHEDULER", "1")
    monkeypatch.setenv("LOG_TO_STDOUT_ONLY", "1")

    from logging_config import reset_logging_config, configure_logging

    reset_logging_config()
    configure_logging("test-health")

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


def test_health_live_ok(app_client):
    rv = app_client.get("/api/health")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["status"] == "ok"
    assert data.get("check") == "live"


def test_health_live_alias(app_client):
    rv = app_client.get("/api/health/live")
    assert rv.status_code == 200
    assert rv.get_json().get("check") == "live"


def test_health_ready_ok(app_client):
    rv = app_client.get("/api/health/ready")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data.get("ready") is True
    assert data.get("database") == "ok"
    assert "enrichment_backlog" in data
