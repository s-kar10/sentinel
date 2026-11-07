"""Durable queue contracts, including concurrent SQLite/PostgreSQL consumers."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_engine_v2 import pack, spec
from test_migrations import migration_engine  # noqa: F401

from app.attacks.packs import AttackPack
from app.database.migrations import migrate
from app.models import EvaluationRun, TargetApplication
from app.models import TestResult as Result
from app.models.job import EvaluationJob
from app.services.job_service import LEASE_SECONDS, JobService, error_result
from app.worker import execute_claim, run_once


@pytest.fixture
def queue_factory(migration_engine):  # noqa: F811
    migrate(migration_engine, "upgrade")
    return sessionmaker(bind=migration_engine, expire_on_commit=False, autoflush=False)


def target(factory, name="Target"):
    with factory() as db:
        item = TargetApplication(
            name=name,
            endpoint_url="http://127.0.0.1:1/chat",
            http_method="POST",
            api_key="FAKE_KEY",
            request_template={"message": ""},
            prompt_field="message",
            response_field="response",
        )
        db.add(item)
        db.commit()
        return item.id


def submit(factory, target_id, key=None, count=1):
    definition = pack(spec("exact_match", {"values": ["SAFE"]}))
    definition["attacks"] = [
        {**definition["attacks"][0], "id": f"check-{i}"} for i in range(count)
    ]
    with factory() as db:
        return (
            JobService(db)
            .submit(
                target_id,
                attack_pack=AttackPack.model_validate(definition),
                idempotency_key=key,
            )
            .id
        )


def result(outcome="passed"):
    return {
        **error_result("Synthetic"),
        "outcome_code": outcome,
        "passed": outcome == "passed",
        "response": "SAFE",
        "duration_ms": 12,
    }


def claim(factory, now):
    with factory() as db:
        return JobService(db).claim(now=now)


def finish(factory, lease, now, **kwargs):
    with factory() as db:
        return JobService(db).finish(
            lease, kwargs.pop("data", result()), now=now, **kwargs
        )


def test_prompt_submission_and_no_outbound_contact(api_client, valid_target_payload):
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    with patch(
        "app.services.target_client.TargetClient.send_prompt",
        side_effect=AssertionError("No HTTP during submit"),
    ):
        start = time.monotonic()
        response = api_client.post(
            f"/targets/{target_id}/evaluation-jobs",
            json={"attack_pack": pack(spec("status_code", {"allowed": [200]}))},
            headers={"Idempotency-Key": "one"},
        )
        assert time.monotonic() - start < 2
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "pending"
    assert run["progress"] == {"planned": 1, "completed": 0, "errored": 0}
    assert "FAKE" not in response.text and "fake-test-key" not in response.text
    assert (
        api_client.get(f"/evaluations/{run['id']}/results").json()[0]["outcome"]
        == "untested"
    )


def test_atomic_submission_rollback(queue_factory):
    tid = target(queue_factory)
    with queue_factory() as db:
        service = JobService(db)
        original = service.evaluations.prepare

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated before queue insert")

        service.evaluations.prepare = fail
        with pytest.raises(RuntimeError):
            service.submit(
                tid,
                attack_pack=AttackPack.model_validate(
                    pack(spec("status_code", {"allowed": [200]}))
                ),
            )
    with queue_factory() as db:
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 0
        assert db.scalar(select(func.count()).select_from(EvaluationJob)) == 0


def test_concurrent_idempotency_and_changed_request(queue_factory):
    tid = target(queue_factory)
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: submit(queue_factory, tid, "same"), range(8)))
    assert len(set(ids)) == 1
    with pytest.raises(Exception, match="different request"):
        submit(queue_factory, tid, "same", 2)
    with queue_factory() as db:
        assert db.scalar(select(func.count()).select_from(Result)) == 1


def test_limits_progress_and_duplicate_delivery(queue_factory):
    tids = [target(queue_factory, f"Target {i}") for i in range(3)]
    runs = [submit(queue_factory, tid, count=2) for tid in tids]
    submit(queue_factory, tids[0])
    now = time.time()
    first = claim(queue_factory, now)
    assert first.run_id == runs[0]
    assert claim(queue_factory, now + 0.1) is None  # Global admission rate.
    assert claim(queue_factory, now + 0.499) is None  # No early boundary admission.
    second = claim(queue_factory, now + 0.5)
    assert second.run_id == runs[1]  # Different target.
    assert claim(queue_factory, now + 1) is None  # Global concurrent limit.
    assert finish(queue_factory, first, now + 1)
    assert not finish(queue_factory, first, now + 1.1, data=result("failed"))
    with queue_factory() as db:
        run = JobService(db).evaluations.get_run(first.run_id)
        assert run.progress == {"planned": 2, "completed": 1, "errored": 0}
        assert run.results[0].outcome == "passed"
        assert len(run.results) == 2
    third = claim(queue_factory, now + 1.5)
    assert third.run_id == runs[2]


def test_same_target_and_simultaneous_claims(queue_factory):
    tid = target(queue_factory)
    submit(queue_factory, tid)
    submit(queue_factory, tid)
    now = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim(queue_factory, now), range(4)))
    assert sum(c is not None for c in claims) == 1
    assert claim(queue_factory, now + 1) is None


def test_crash_recovery_fences_old_worker_and_caps_attempts(queue_factory):
    rid = submit(queue_factory, target(queue_factory))
    now = time.time()
    first = claim(queue_factory, now)
    assert claim(queue_factory, now + 76) is None  # Recovery schedules backoff.
    second = claim(queue_factory, now + 80)
    assert second.token != first.token
    assert not finish(queue_factory, first, now + 81)
    assert claim(queue_factory, now + 156) is None
    third = claim(queue_factory, now + 162)
    assert third
    assert claim(queue_factory, now + 238) is None
    with queue_factory() as db:
        run = JobService(db).evaluations.get_run(rid)
        assert run.status == "completed"
        assert run.progress == {"planned": 1, "completed": 1, "errored": 1}
        assert db.get(EvaluationJob, rid).payload is None
        assert len(run.results) == 1


def test_retry_exhaustion_and_cancel_preserves_partial_evidence(queue_factory):
    rid = submit(queue_factory, target(queue_factory), count=2)
    now = time.time()
    for offset in (0, 4, 10):
        lease = claim(queue_factory, now + offset)
        assert lease and lease.index == 0
        assert finish(
            queue_factory,
            lease,
            now + offset + 0.1,
            data=error_result("Transient failure."),
            retryable=True,
        )
    lease = claim(queue_factory, now + 11)
    assert lease.index == 1
    with queue_factory() as db:
        service = JobService(db)
        cancelled = service.cancel(rid)
        assert cancelled.status == "cancelled"
        assert cancelled.progress == {"planned": 2, "completed": 1, "errored": 1}
        assert service.cancel(rid).status == "cancelled"
        assert not service.active(lease)
    assert not finish(queue_factory, lease, now + 12)


def test_run_deadline_and_target_deletion(queue_factory):
    tid = target(queue_factory)
    rid = submit(queue_factory, tid)
    assert claim(queue_factory, time.time() + 1801) is None
    with queue_factory() as db:
        assert JobService(db).evaluations.get_run(rid).status == "failed"
        assert db.get(EvaluationJob, rid).payload is None
        db.delete(db.get(TargetApplication, tid))
        db.commit()
        assert db.get(EvaluationJob, rid) is None


def test_worker_real_process_and_timeout(session_factory):
    class Handler(BaseHTTPRequestHandler):
        delay = 0

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(self.delay)
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(b'{"response":"SAFE"}')
            except BrokenPipeError:
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        tid = target(session_factory)
        with session_factory() as db:
            db.get(
                TargetApplication, tid
            ).endpoint_url = f"http://127.0.0.1:{server.server_port}/"
            db.commit()
        rid = submit(session_factory, tid)
        assert run_once(session_factory)
        with session_factory() as db:
            assert (
                JobService(db).evaluations.get_run(rid).results[0].outcome == "passed"
            )
        submit(session_factory, tid)
        lease = claim(session_factory, time.time() + 1)
        Handler.delay = 2
        started = time.monotonic()
        data, retryable = execute_claim(replace(lease, timeout=0.1), lambda: True)
        assert time.monotonic() - started < 1
        assert data["outcome_code"] == "errored" and retryable
        assert execute_claim(lease, lambda: False) is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bounded_multiworker_workload(queue_factory):
    """Eight 0.8-second synthetic cases, two targets, four concurrent consumers."""
    import threading

    tid1, tid2 = target(queue_factory, "One"), target(queue_factory, "Two")
    ids = [submit(queue_factory, tid1, count=4), submit(queue_factory, tid2, count=4)]
    mutex = threading.Lock()
    active_targets = set()
    admissions = []
    maximum = 0
    errors = []

    def execute(lease, active):
        nonlocal maximum
        name = lease.payload["target"]["name"]
        # Executor callbacks can start late or bunch together after OS scheduling.
        # The durable lease records the admission time governed by the rate limit.
        with queue_factory() as db:
            job = db.get(EvaluationJob, lease.run_id)
            assert job.token == lease.token
            admitted_at = job.lease_until - LEASE_SECONDS
        with mutex:
            if name in active_targets:
                errors.append("overlapping target")
            active_targets.add(name)
            maximum = max(maximum, len(active_targets))
            admissions.append(admitted_at)
        assert active()
        time.sleep(0.8)
        with mutex:
            active_targets.remove(name)
        return result(), False

    def consume():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run_once(queue_factory, execute)
            with queue_factory() as db:
                if all(db.get(EvaluationRun, rid).status == "completed" for rid in ids):
                    return
            time.sleep(0.05)
        raise AssertionError("Workload did not finish")

    with ThreadPoolExecutor(max_workers=4) as pool:
        for task in [pool.submit(consume) for _ in range(4)]:
            task.result()
    assert not errors and maximum <= 2
    assert len(admissions) == 8
    ordered = sorted(admissions)
    assert all(b - a >= 0.5 for a, b in zip(ordered, ordered[1:]))


def test_retry_classification_and_frozen_transport_policy(session_factory):
    import httpx

    from app.case_worker import execute
    from app.core.config import Settings
    from app.services.target_client import TargetClient

    tid = target(session_factory)
    with session_factory() as db:
        service = JobService(db, Settings(target_request_timeout_seconds=2))
        rid = service.submit(
            tid,
            attack_pack=AttackPack.model_validate(
                pack(spec("exact_match", {"values": ["SAFE"]}))
            ),
        ).id
        payload = db.get(EvaluationJob, rid).payload
        assert payload["transport"]["timeout_seconds"] == 2
        db.get(TargetApplication, tid).endpoint_url = "http://example.invalid/changed"
        db.commit()
        assert payload["target"]["endpoint_url"] == "http://127.0.0.1:1/chat"
    real_client = TargetClient
    for status, retryable in ((503, True), (429, True), (400, False), (200, False)):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda _, code=status: httpx.Response(code, json={"response": "SAFE"})
            )
        )
        with (
            client,
            patch(
                "app.case_worker.TargetClient",
                side_effect=lambda target, **kwargs: real_client(
                    target, **kwargs, http_client=client
                ),
            ),
        ):
            assert execute(payload, 0)["retryable"] is retryable


def test_version_secret_rejected_and_idempotency_conflict(
    api_client, valid_target_payload
):
    tid = api_client.post("/targets", json=valid_target_payload).json()["id"]
    body = {
        "attack_pack": pack(spec("status_code", {"allowed": [200]})),
        "versions": {"application": "fake-test-key"},
    }
    response = api_client.post(f"/targets/{tid}/evaluation-jobs", json=body)
    assert response.status_code == 422 and "fake-test-key" not in response.text
    assert api_client.get("/evaluations").json() == []
    body["versions"] = {"application": "v1"}
    headers = {"Idempotency-Key": "version-test"}
    assert (
        api_client.post(
            f"/targets/{tid}/evaluation-jobs", json=body, headers=headers
        ).status_code
        == 202
    )
    body["versions"] = {"application": "v2"}
    assert (
        api_client.post(
            f"/targets/{tid}/evaluation-jobs", json=body, headers=headers
        ).status_code
        == 409
    )


def test_child_own_deadline_survives_without_supervisor(session_factory):
    import json
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path

    class SlowHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(3)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        tid = target(session_factory)
        with session_factory() as db:
            db.get(
                TargetApplication, tid
            ).endpoint_url = f"http://127.0.0.1:{server.server_port}/"
            db.commit()
        submit(session_factory, tid)
        lease = claim(session_factory, time.time())
        # No app.worker parent supplies a timer; only the case process can stop itself.
        output = subprocess.run(
            [sys.executable, "-m", "app.case_worker"],
            input=json.dumps(
                {"payload": lease.payload, "index": 0, "timeout": 0.2}
            ).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).resolve().parents[1],
            env={"PATH": os.defpath},
            start_new_session=True,
            timeout=3,
        )
        assert output.returncode == -signal.SIGKILL
        assert not output.stdout and not output.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
