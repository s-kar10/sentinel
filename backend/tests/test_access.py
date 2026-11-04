"""Operator token lifecycle and default-deny API boundaries using migrated data."""

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth import cli
from app.auth.policy import PUBLIC_GET, permits, required_role
from app.auth.tokens import Role, authenticate, digest, issue, revoke
from app.core.config import Settings
from app.database.session import get_db
from app.main import create_app
from app.models.access import AccessAudit, AccessToken


@pytest.fixture
def guarded(test_engine, session_factory):
    app = create_app(
        Settings(auth_mode="token", _env_file=None), database_engine=test_engine
    )

    def db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    tokens = {}
    with Session(test_engine) as session:
        for role in Role:
            row, value = issue(session, role.value, role)
            tokens[role.value] = (row.id, value)
        session.commit()
    with TestClient(app) as client:
        yield app, client, tokens


def bearer(tokens, role):
    return {"Authorization": "Bearer " + tokens[role][1]}


def test_role_policy_covers_every_application_route(guarded):
    app, _, _ = guarded
    for route in app.routes:
        path = route.path
        for parameter in ("target_id", "protected_value_id", "evaluation_id"):
            path = path.replace("{" + parameter + "}", "1")
        for method in route.methods:
            if method == "HEAD" and path == "/openapi.json":
                continue
            if method == "GET" and path in PUBLIC_GET:
                continue
            if method == "POST" and path == "/targets/1/evaluations":
                assert required_role(method, path) is None
                continue
            assert required_role(method, path) is not None, (method, route.path)
    assert not permits(Role.ADMIN, "POST", "/future-admin-endpoint")
    assert not permits(Role.ADMIN, "GET", "/future-sensitive-export")


@pytest.mark.parametrize(
    "path",
    [
        "/targets",
        "/targets/1",
        "/targets/1/protected-values",
        "/attack-packs",
        "/evaluations",
        "/evaluations/1",
        "/evaluations/1/results",
        "/targets/1/baselines",
        "/evaluations/1/comparison",
        "/targets/1/analytics",
        "/openapi.json",
        "/docs",
        "/auth/me",
        "/targets/",
    ],
)
def test_anonymous_reads_are_rejected(guarded, path):
    _, client, _ = guarded
    result = client.get(path)
    assert result.status_code == 401
    assert result.headers["www-authenticate"] == "Bearer"
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/targets"),
        ("PUT", "/targets/1"),
        ("DELETE", "/targets/1"),
        ("POST", "/targets/1/protected-values"),
        ("DELETE", "/protected-values/1"),
        ("POST", "/targets/1/evaluation-jobs"),
        ("POST", "/targets/1/evaluations"),
        ("POST", "/evaluations/1/cancel"),
        ("POST", "/targets/1/baselines"),
    ],
)
def test_writes_authorize_before_parsing_untrusted_input(guarded, method, path):
    _, client, tokens = guarded
    for headers, expected in [({}, 401), (bearer(tokens, "reader"), 403)]:
        response = client.request(
            method, path, headers=headers, content=b'{"private":"SYNTHETIC_AUTH_SECRET"'
        )
        assert response.status_code == expected
        assert "SYNTHETIC_AUTH_SECRET" not in response.text


def test_roles_run_the_same_authorized_target_workflow(
    guarded, valid_target_payload, test_engine
):
    _, client, tokens = guarded
    admin, reader, runner = [
        bearer(tokens, role) for role in ("admin", "reader", "runner")
    ]
    assert (
        client.post("/targets", headers=runner, json=valid_target_payload).status_code
        == 403
    )
    result = client.post("/targets", headers=admin, json=valid_target_payload)
    assert result.status_code == 201
    target_id = result.json()["id"]
    assert len(client.get("/targets", headers=reader).json()) == 1
    pack = client.get("/attack-packs", headers=reader).json()[1]
    run = client.post(
        f"/targets/{target_id}/evaluation-jobs",
        headers=runner,
        json={"attack_pack": pack},
    )
    assert run.status_code == 202
    run_id = run.json()["id"]
    from app.models.job import EvaluationJob

    with Session(test_engine) as db:
        payload = json.dumps(db.get(EvaluationJob, run_id).payload)
        assert all(value not in payload for _, value in tokens.values())
    assert (
        client.get(f"/evaluations/{run_id}/results", headers=reader).status_code == 200
    )
    assert (
        client.post(f"/evaluations/{run_id}/cancel", headers=reader).status_code == 403
    )
    assert (
        client.post(f"/evaluations/{run_id}/cancel", headers=runner).status_code == 200
    )
    # Even admin tokens cannot bypass durable queue limits via the legacy route.
    assert (
        client.post(f"/targets/{target_id}/evaluations", headers=admin).status_code
        == 403
    )
    assert client.delete(f"/targets/{target_id}", headers=runner).status_code == 403
    assert client.delete(f"/targets/{target_id}", headers=admin).status_code == 204
    for role in tokens:
        identity = client.get("/auth/me", headers=bearer(tokens, role))
        assert identity.json() == {
            "name": role,
            "role": role,
            "token_id": tokens[role][0],
        }
        assert tokens[role][1] not in identity.text
        assert identity.headers["cache-control"] == "no-store"


def test_token_expiry_revocation_and_rotation_are_checked_per_request(
    guarded, test_engine
):
    _, client, tokens = guarded
    with Session(test_engine) as db:
        old_id, old = tokens["admin"]
        replacement, value = issue(db, "replacement", Role.ADMIN)
        replacement_id = replacement.id
        db.commit()
        assert (
            client.get(
                "/targets", headers={"Authorization": "Bearer " + value}
            ).status_code
            == 200
        )
        assert revoke(db, old_id)
        assert not revoke(db, old_id)
        db.commit()
        assert (
            client.get(
                "/targets", headers={"Authorization": "Bearer " + old}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/targets", headers={"Authorization": "Bearer " + value}
            ).status_code
            == 200
        )
        db.get(AccessToken, replacement_id).expires_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        db.commit()
        assert (
            client.get(
                "/targets", headers={"Authorization": "Bearer " + value}
            ).status_code
            == 401
        )
        rows = list(
            db.scalars(select(AccessAudit).where(AccessAudit.token_id == old_id))
        )
        assert [row.event for row in rows] == ["issued", "revoked"]
        assert db.get(AccessToken, old_id).digest == digest(old)
        assert db.get(AccessToken, old_id).digest != old


def test_bad_headers_queries_and_cookies_never_authenticate(guarded):
    _, client, tokens = guarded
    value = tokens["admin"][1]
    for headers in [
        {"Authorization": "Basic " + value},
        {"Authorization": "Bearer " + "x" * 1000},
        {"Authorization": "Bearer " + value + " extra"},
        [("Authorization", "Bearer " + value), ("Authorization", "Bearer " + value)],
        {"Cookie": "access_token=" + value},
    ]:
        response = client.get("/targets", headers=headers)
        assert response.status_code == 401
        assert value not in response.text
    assert client.get("/targets", params={"token": value}).status_code == 401


def test_auth_database_failure_is_closed_and_redacted(guarded, monkeypatch):
    from app.auth.middleware import AccessMiddleware

    _, client, tokens = guarded
    monkeypatch.setattr(
        AccessMiddleware,
        "lookup",
        Mock(side_effect=OperationalError("SYNTHETIC_PRIVATE_DB", {}, None)),
    )
    response = client.get("/targets", headers=bearer(tokens, "admin"))
    assert response.status_code == 503
    assert response.json() == {"detail": "Access verification is unavailable."}
    assert "SYNTHETIC_PRIVATE_DB" not in response.text


def test_health_mode_and_cors_preflight_do_not_expose_application_data(guarded):
    _, client, _ = guarded
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/auth/status").json() == {"mode": "token"}
    result = client.options(
        "/targets",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert result.status_code == 200
    assert (
        client.get("/targets", headers={"Origin": "http://localhost:3000"}).status_code
        == 401
    )


def test_local_mode_is_explicitly_development_only(api_client):
    assert api_client.get("/auth/status").json() == {"mode": "local"}
    assert api_client.get("/auth/me").json()["role"] == "admin"
    with pytest.raises(ValidationError, match="only allowed in development"):
        Settings(auth_mode="local", app_environment="production", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(auth_mode="typo", _env_file=None)


def test_cli_private_file_no_echo_listing_revocation_and_rollback(
    test_engine, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "build_engine", lambda _: test_engine)
    output = tmp_path / "credential"
    args = ["issue", "--name", "operator", "--role", "admin", "--output", str(output)]
    assert cli.main(args) == 0
    value = output.read_text().strip()
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert value not in capsys.readouterr().out
    assert cli.main(args) == 1  # No overwrite, no extra DB row.
    assert output.read_text().strip() == value
    assert cli.main(["list"]) == 0
    listing = capsys.readouterr().out
    assert value not in listing and digest(value) not in listing
    assert len(json.loads(listing)) == 1
    with Session(test_engine) as db:
        identity = authenticate(db, value)
        token_id = identity.token_id
    assert cli.main(["revoke", str(token_id)]) == 0
    assert cli.main(["revoke", str(token_id)]) == 0
    capsys.readouterr()
    assert cli.main(["audit"]) == 0
    assert [e["event"] for e in json.loads(capsys.readouterr().out)] == [
        "issued",
        "revoked",
    ]
    invalid_path = tmp_path / "invalid"
    assert cli.main([*args[:-1], str(invalid_path), "--days", "91"]) == 1
    assert not invalid_path.exists()
    with Session(test_engine) as db:
        assert authenticate(db, value) is None
        assert len(list(db.scalars(select(AccessToken)))) == 1


def test_openapi_documents_bearer_without_exposing_credentials(guarded):
    _, client, tokens = guarded
    response = client.get("/openapi.json", headers=bearer(tokens, "reader"))
    assert response.status_code == 200
    schema = response.json()
    assert (
        schema["components"]["securitySchemes"]["OperatorToken"]["scheme"] == "bearer"
    )
    assert schema["paths"]["/targets"]["get"]["security"] == [{"OperatorToken": []}]
    assert "security" not in schema["paths"]["/auth/status"]["get"]
    assert all(value not in response.text for _, value in tokens.values())
