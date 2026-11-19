"""Request-body bounds, project-aware queued admission and fair dispatch."""

# Imported pytest fixtures are intentionally named in test signatures.
# ruff: noqa: F811

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from test_engine_v2 import pack, spec
from test_jobs import queue_factory, result  # noqa: F401
from test_migrations import migration_engine  # noqa: F401

from app.api.body_limit import RequestBodyLimitMiddleware
from app.attacks.packs import AttackPack
from app.core.config import Settings
from app.database.session import get_db
from app.main import create_app
from app.models import EvaluationRun, TargetApplication
from app.models.job import EvaluationJob
from app.models.project import Project
from app.services.errors import CapacityError
from app.services.job_service import JobService

SMALL_BODY = 65_536


def limited_client(test_engine, session_factory, **overrides):
    settings = Settings(
        database_url="sqlite://",
        cors_origins="http://localhost:3000",
        _env_file=None,
        **overrides,
    )
    application = create_app(settings, database_engine=test_engine)

    def session():
        with session_factory() as db:
            yield db

    application.dependency_overrides[get_db] = session
    return TestClient(application)


def count(factory, model):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model))


# --- Request bodies ---------------------------------------------------------


def oversized_target(payload):
    return {**payload, "request_template": {"message": "", "pad": "x" * SMALL_BODY}}


def test_declared_oversized_body_rejected_before_parsing(
    test_engine, session_factory, valid_target_payload
):
    with limited_client(
        test_engine, session_factory, max_request_body_bytes=SMALL_BODY
    ) as client:
        accepted = client.post("/targets", json=valid_target_payload)
        assert accepted.status_code == 201
        response = client.post("/targets", json=oversized_target(valid_target_payload))
        assert response.status_code == 413
        assert response.json() == {
            "detail": "The request body exceeds the configured size limit."
        }
        assert "fake-test-key" not in response.text
    assert count(session_factory, TargetApplication) == 1


def test_streamed_body_without_length_is_cut_off(
    test_engine, session_factory, valid_target_payload
):
    import json

    encoded = json.dumps(oversized_target(valid_target_payload)).encode()
    chunks_sent = []

    def stream():
        for start in range(0, len(encoded), 8_192):
            chunks_sent.append(start)
            yield encoded[start : start + 8_192]

    with limited_client(
        test_engine, session_factory, max_request_body_bytes=SMALL_BODY
    ) as client:
        response = client.post(
            "/targets",
            content=stream(),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert count(session_factory, TargetApplication) == 0


def test_token_mode_authenticates_before_body_limit(test_engine, session_factory):
    application = create_app(
        Settings(auth_mode="token", max_request_body_bytes=SMALL_BODY, _env_file=None),
        database_engine=test_engine,
    )
    with TestClient(application) as client:
        response = client.post("/targets", content=b"x" * (SMALL_BODY + 1))
    assert response.status_code == 401


def call_middleware(headers, chunks, max_bytes=10):
    """Drive the ASGI layer directly with a plain body-reading application."""

    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    sent = []
    consumed = []

    async def application(scope, receive, send):
        while True:
            message = await receive()
            consumed.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers}
    middleware = RequestBodyLimitMiddleware(application, max_bytes=max_bytes)
    asyncio.run(middleware(scope, receive, send))
    return sent[0]["status"], consumed


@pytest.mark.parametrize(
    ("headers", "chunks", "status", "read"),
    [
        ([(b"content-length", b"10")], [b"x" * 10], 204, 1),
        ([(b"content-length", b"11")], [b"x" * 11], 413, 0),
        ([(b"content-length", b"4"), (b"content-length", b"5")], [b"x"], 400, 0),
        ([(b"content-length", b"-1")], [b"x"], 400, 0),
        ([(b"content-length", b"9" * 40)], [b"x"], 400, 0),
        ([], [b"x" * 6, b"x" * 6, b"x" * 6], 413, 1),
        ([], [b"x" * 5, b"x" * 5], 204, 2),
    ],
)
def test_body_limit_edges(headers, chunks, status, read):
    actual, consumed = call_middleware(headers, chunks)
    assert actual == status
    # A rejected stream stops at the chunk crossing the limit; declared
    # oversize/invalid lengths are rejected without consuming any body.
    assert len(consumed) == read


def test_limit_settings_are_bounded_and_consistent():
    with pytest.raises(ValidationError):
        Settings(max_request_body_bytes=1_024, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(queue_max_active_runs_per_project=0, _env_file=None)
    with pytest.raises(ValidationError, match="per-project queue limit"):
        Settings(
            queue_max_active_runs_per_project=20,
            queue_max_active_runs=10,
            _env_file=None,
        )


# --- Queued admission -------------------------------------------------------


def project_target(factory, project_id, name):
    with factory() as db:
        if db.get(Project, project_id) is None:
            db.add(
                Project(id=project_id, name=f"Project {project_id}", organization_id=1)
            )
            db.flush()
        item = TargetApplication(
            name=name,
            endpoint_url="http://127.0.0.1:1/chat",
            http_method="POST",
            request_template={"message": ""},
            prompt_field="message",
            response_field="response",
            project_id=project_id,
        )
        db.add(item)
        db.commit()
        return item.id


def submit(factory, target_id, settings, key=None):
    with factory() as db:
        return (
            JobService(db, settings)
            .submit(
                target_id,
                attack_pack=AttackPack.model_validate(
                    pack(spec("exact_match", {"values": ["SAFE"]}))
                ),
                idempotency_key=key,
            )
            .id
        )


def limits(project, total):
    return Settings(
        queue_max_active_runs_per_project=project,
        queue_max_active_runs=total,
        _env_file=None,
    )


def test_project_and_installation_admission_quotas(queue_factory):
    settings = limits(project=2, total=3)
    first = project_target(queue_factory, 1, "First")
    second = project_target(queue_factory, 2, "Second")
    accepted = [
        submit(queue_factory, first, settings, key="a"),
        submit(queue_factory, first, settings),
    ]
    with pytest.raises(CapacityError, match="This project already has 2"):
        submit(queue_factory, first, settings)
    # Replaying an accepted request is not a new admission.
    assert submit(queue_factory, first, settings, key="a") == accepted[0]
    # A sibling project keeps its own allowance until the installation is full.
    submit(queue_factory, second, settings)
    with pytest.raises(CapacityError, match="queue is at capacity"):
        submit(queue_factory, second, settings)
    assert count(queue_factory, EvaluationRun) == 3
    assert count(queue_factory, EvaluationJob) == 3

    with queue_factory() as db:
        JobService(db).cancel(accepted[1])
    submit(queue_factory, second, settings)  # Cancellation frees capacity.
    with queue_factory() as db:
        db.get(EvaluationJob, accepted[0]).deadline = time.time() - 1
        db.commit()
    # Work past its run deadline can no longer execute and does not hold quota.
    submit(queue_factory, first, settings)


def test_concurrent_submissions_cannot_overshoot_quota(queue_factory):
    settings = limits(project=3, total=50)
    tid = project_target(queue_factory, 1, "Burst")

    def attempt(_):
        try:
            return submit(queue_factory, tid, settings)
        except CapacityError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt, range(10)))
    assert sum(item is not None for item in outcomes) == 3
    assert count(queue_factory, EvaluationJob) == 3
    assert count(queue_factory, EvaluationRun) == 3


def test_api_reports_quota_as_429(test_engine, session_factory, valid_target_payload):
    with limited_client(
        test_engine,
        session_factory,
        queue_max_active_runs_per_project=1,
    ) as client:
        tid = client.post("/targets", json=valid_target_payload).json()["id"]
        body = {"attack_pack": pack(spec("status_code", {"allowed": [200]}))}
        url = f"/targets/{tid}/evaluation-jobs"
        assert client.post(url, json=body).status_code == 202
        rejected = client.post(url, json=body)
        assert rejected.status_code == 429
        assert "unfinished queued evaluations" in rejected.json()["detail"]
        assert len(client.get("/evaluations").json()) == 1


# --- Fair dispatch ----------------------------------------------------------


def test_dispatch_prefers_projects_without_active_leases(queue_factory):
    settings = limits(project=10, total=10)
    busy_one = project_target(queue_factory, 1, "Busy one")
    busy_two = project_target(queue_factory, 1, "Busy two")
    quiet = project_target(queue_factory, 2, "Quiet")
    busy_runs = [submit(queue_factory, busy_one, settings)]
    busy_runs.append(submit(queue_factory, busy_two, settings))
    quiet_run = submit(queue_factory, quiet, settings)

    now = time.time()
    with queue_factory() as db:
        first = JobService(db).claim(now=now)
    assert first.run_id == busy_runs[0]
    with queue_factory() as db:
        second = JobService(db).claim(now=now + 0.5)
    # FIFO would pick the older second project-1 target; fairness picks project 2.
    assert second.run_id == quiet_run
    with queue_factory() as db:
        assert JobService(db).finish(first, result(), now=now + 0.6)
        third = JobService(db).claim(now=now + 1)
    assert third.run_id == busy_runs[1]  # Work-conserving once slots free up.
