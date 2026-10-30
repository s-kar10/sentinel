"""Readiness, failure redaction, recovery, and browser origin contracts."""

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.database.migrations import migration_config
from app.main import create_app


def test_ready_checks_injected_database(api_client):
    response = api_client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "sentinel-api"}
    assert response.headers["cache-control"] == "no-store"


def test_outage_is_redacted_and_liveness_does_not_connect(
    api_client, test_engine, monkeypatch, caplog
):
    def fail():
        raise OperationalError("FAKE_SECRET_SQL", {}, Exception("FAKE_PASSWORD"))

    with monkeypatch.context() as patch:
        patch.setattr(test_engine, "connect", fail)
        assert api_client.get("/health").status_code == 200
        response = api_client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "service": "sentinel-api"}
        assert "FAKE_" not in response.text + caplog.text
    assert api_client.get("/ready").status_code == 200


@pytest.mark.parametrize("revision", [None, "unknown_revision"])
def test_runtime_schema_drift_is_not_repaired(api_client, test_engine, revision):
    with test_engine.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
        if revision:
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
    assert api_client.get("/ready").status_code == 503
    assert api_client.get("/health").status_code == 200
    with test_engine.begin() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).all() == ([(revision,)] if revision else [])
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {
                "revision": ScriptDirectory.from_config(
                    migration_config()
                ).get_current_head()
            },
        )
    assert api_client.get("/ready").status_code == 200


def test_missing_version_table_is_not_created(api_client, test_engine):
    with test_engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    assert api_client.get("/ready").status_code == 503
    assert "alembic_version" not in inspect(test_engine).get_table_names()


@pytest.mark.parametrize(
    ("configured", "origin", "allowed"),
    [
        (None, "http://localhost:3000", True),
        (None, "http://127.0.0.1:3000", True),
        (None, "http://localhost:5173", False),
        ("http://localhost:4300", "http://localhost:4300", True),
        ("http://localhost:4300", "http://localhost:3000", False),
    ],
)
def test_native_and_custom_cors(test_engine, monkeypatch, configured, origin, allowed):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(
        _env_file=None, **({"cors_origins": configured} if configured else {})
    )
    with TestClient(create_app(settings, database_engine=test_engine)) as client:
        response = client.options(
            "/targets",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == (200 if allowed else 400)
    assert response.headers.get("access-control-allow-origin") == (
        origin if allowed else None
    )
