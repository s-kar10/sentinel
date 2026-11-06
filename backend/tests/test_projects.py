"""Project isolation across API, queue ownership, migrations and local provisioning."""

# Imported pytest fixtures are intentionally named in test signatures.
# ruff: noqa: F811

import json
import time
from unittest.mock import patch

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_engine_v2 import pack, spec
from test_jobs import queue_factory, result  # noqa: F401
from test_judges import owned_provider  # noqa: F401
from test_migrations import migration_engine, seed_records  # noqa: F401

from app.auth import cli
from app.auth.tokens import Role, authenticate, digest, issue
from app.core.config import Settings
from app.database.migrations import migrate, migration_config
from app.database.session import get_db
from app.main import create_app
from app.models import EvaluationRun, TargetApplication
from app.models.access import AccessToken
from app.models.job import EvaluationJob
from app.models.project import Organization, Project, TargetProject, TokenProject
from app.services.job_service import JobService


@pytest.fixture
def projects(queue_factory):  # noqa: F811
    with queue_factory() as db:
        org = Organization(name="Other organization")
        db.add(org)
        db.flush()
        same = Project(name="Second project", organization_id=1)
        other = Project(name="Other project", organization_id=org.id)
        db.add_all([same, other])
        db.flush()
        ids = [1, same.id, other.id]
        headers = {}
        for project_id in ids:
            for role in Role:
                _, token = issue(
                    db, f"Project {project_id} {role}", role, project_id=project_id
                )
                headers[project_id, role] = {"Authorization": "Bearer " + token}
        db.commit()
    app = create_app(
        Settings(auth_mode="token", _env_file=None),
        database_engine=queue_factory.kw["bind"],
    )

    def session():
        with queue_factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        yield client, ids, headers


def make_target(client, headers, payload, name):
    response = client.post("/targets", headers=headers, json={**payload, "name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def make_run(client, headers, target_id):
    response = client.post(
        f"/targets/{target_id}/evaluation-jobs",
        headers=headers,
        json={"attack_pack": pack(spec("exact_match", {"values": ["SAFE"]}))},
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def complete(factory, count):
    now = time.time() + 2
    for offset in range(count):
        with factory() as db:
            service = JobService(db)
            claim = service.claim(now=now + offset)
            assert claim
            assert service.finish(claim, result(), now=now + offset + 0.1)


def test_all_resource_paths_hide_other_projects(
    projects, queue_factory, valid_target_payload
):
    client, ids, headers = projects
    resources = []
    for pid in ids:
        admin = headers[pid, Role.ADMIN]
        tid = make_target(client, admin, valid_target_payload, f"Private project {pid}")
        protected = client.post(
            f"/targets/{tid}/protected-values",
            headers=admin,
            json={"name": f"Private canary {pid}", "value": f"SYNTHETIC_PRIVATE_{pid}"},
        ).json()["id"]
        rid = make_run(client, admin, tid)
        resources.append((tid, protected, rid))
    complete(queue_factory, 3)
    baselines = []
    for pid, (tid, _, rid) in zip(ids, resources):
        response = client.post(
            f"/targets/{tid}/baselines",
            headers=headers[pid, Role.RUNNER],
            json={"run_id": rid, "name": "private baseline"},
        )
        assert response.status_code == 201, response.text
        baselines.append(response.json()["id"])
    for i, pid in enumerate(ids):
        own_tid, _, own_rid = resources[i]
        for role in Role:
            auth = headers[pid, role]
            assert [t["id"] for t in client.get("/targets", headers=auth).json()] == [
                own_tid
            ]
            assert [
                r["id"] for r in client.get("/evaluations", headers=auth).json()
            ] == [own_rid]
            assert (
                client.get(
                    f"/evaluations/{own_rid}/comparison?baseline_id={baselines[i]}",
                    headers=auth,
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"/targets/{own_tid}/analytics?baseline_id={baselines[i]}",
                    headers=auth,
                ).status_code
                == 200
            )
            for j, (tid, protected, rid) in enumerate(resources):
                if i == j:
                    continue
                for path in [
                    f"/targets/{tid}",
                    f"/targets/{tid}/protected-values",
                    f"/evaluations/{rid}",
                    f"/evaluations/{rid}/results",
                    f"/targets/{tid}/baselines",
                    f"/targets/{tid}/analytics?baseline_id={baselines[j]}",
                    f"/evaluations/{own_rid}/comparison?baseline_id={baselines[j]}",
                    f"/evaluations/{rid}/comparison?baseline_id={baselines[i]}",
                ]:
                    response = client.get(path, headers=auth)
                    assert response.status_code == 404, (role, path, response.text)
                    assert "Private" not in response.text
                assert (
                    client.get(f"/evaluations?target_id={tid}", headers=auth).json()
                    == []
                )
                if role == Role.ADMIN:
                    for method, path, body in [
                        ("PUT", f"/targets/{tid}", {"name": "stolen"}),
                        ("DELETE", f"/targets/{tid}", None),
                        ("DELETE", f"/protected-values/{protected}", None),
                        (
                            "POST",
                            f"/targets/{tid}/protected-values",
                            {"name": "bad", "value": "FAKE"},
                        ),
                    ]:
                        assert (
                            client.request(
                                method, path, headers=auth, json=body
                            ).status_code
                            == 404
                        )
                if role != Role.READER:
                    for path, body in [
                        (f"/targets/{tid}/evaluation-jobs", None),
                        (f"/evaluations/{rid}/cancel", None),
                        (
                            f"/targets/{own_tid}/baselines",
                            {"run_id": rid, "name": "bad"},
                        ),
                        (
                            f"/targets/{tid}/baselines",
                            {"run_id": own_rid, "name": "bad"},
                        ),
                    ]:
                        assert (
                            client.post(path, headers=auth, json=body).status_code
                            == 404
                        )
        # Header/query/body selectors never widen a token's immutable scope.
        auth = {**headers[pid, Role.ADMIN], "X-Project-ID": str(ids[(i + 1) % 3])}
        assert len(client.get("/targets?project_id=999", headers=auth).json()) == 1
        client.put(f"/targets/{own_tid}", headers=auth, json={"project_id": 999})
        with queue_factory() as db:
            assert db.get(TargetApplication, own_tid).project_id == pid
    # Existing foreign IDs and nonexistent IDs must have indistinguishable errors.
    auth = headers[ids[0], Role.ADMIN]
    foreign_tid, foreign_value, foreign_run = resources[1]
    for method, foreign, missing in [
        ("GET", f"/targets/{foreign_tid}", "/targets/999999"),
        ("GET", f"/evaluations/{foreign_run}", "/evaluations/999999"),
        ("DELETE", f"/protected-values/{foreign_value}", "/protected-values/999999"),
        ("POST", f"/evaluations/{foreign_run}/cancel", "/evaluations/999999/cancel"),
        (
            "GET",
            f"/evaluations/{resources[0][2]}/comparison?baseline_id={baselines[1]}",
            f"/evaluations/{resources[0][2]}/comparison?baseline_id=999999",
        ),
    ]:
        assert (
            client.request(method, foreign, headers=auth).json()
            == client.request(method, missing, headers=auth).json()
        )
    with queue_factory() as db:
        assert len(list(db.scalars(select(EvaluationRun)))) == 3
        assert all(
            db.get(EvaluationRun, rid).status == "completed" for _, _, rid in resources
        )


def test_idempotency_cannot_probe_foreign_job(projects, valid_target_payload):
    client, ids, headers = projects
    owner, stranger = [headers[p, Role.ADMIN] for p in ids[:2]]
    tid = make_target(client, owner, valid_target_payload, "Owned")
    auth = {**owner, "Idempotency-Key": "shared-key"}
    body = {"attack_pack": pack(spec("exact_match", {"values": ["SAFE"]}))}
    first = client.post(f"/targets/{tid}/evaluation-jobs", headers=auth, json=body)
    assert first.status_code == 202
    for foreign_body in [body, {**body, "versions": {"model": "changed"}}]:
        response = client.post(
            f"/targets/{tid}/evaluation-jobs",
            headers={**stranger, "Idempotency-Key": "shared-key"},
            json=foreign_body,
        )
        assert response.status_code == 404
    assert (
        client.post(f"/targets/{tid}/evaluation-jobs", headers=auth, json=body).json()[
            "id"
        ]
        == first.json()["id"]
    )


def test_worker_rejects_mismatched_scope_before_dispatch_and_checkpoint(
    projects, queue_factory, valid_target_payload
):
    client, ids, headers = projects
    admin = headers[ids[1], Role.ADMIN]
    tid = make_target(client, admin, valid_target_payload, "Second project job")
    rid = make_run(client, admin, tid)
    with queue_factory() as db:
        job = db.get(EvaluationJob, rid)
        assert job.payload["target"]["project_id"] == ids[1]
        assert "Bearer" not in json.dumps(job.payload)
        payload = {
            **job.payload,
            "target": {**job.payload["target"], "project_id": ids[0]},
        }
        job.payload = payload
        db.commit()
        assert JobService(db).claim() is None
        assert db.get(EvaluationRun, rid).status == "failed"
        assert db.get(EvaluationJob, rid).payload is None
    second = make_run(client, admin, tid)
    with queue_factory() as db:
        service = JobService(db)
        claim = service.claim()
        assert claim.run_id == second
        job = db.get(EvaluationJob, second)
        job.payload = {**job.payload, "target": {**job.payload["target"], "id": 999}}
        db.commit()
        assert not service.active(claim)
        assert not service.finish(claim, result())
        assert db.get(EvaluationRun, second).results[0].outcome == "untested"


def test_unbound_resources_fail_closed(projects, queue_factory, valid_target_payload):
    client, ids, headers = projects
    auth = headers[ids[0], Role.ADMIN]
    tid = make_target(client, auth, valid_target_payload, "Unbound")
    with queue_factory() as db:
        db.delete(db.get(TargetProject, tid))
        db.commit()
    assert client.get(f"/targets/{tid}", headers=auth).status_code == 404
    assert client.get("/targets", headers=auth).json() == []
    with queue_factory() as db:
        token = db.scalar(
            select(AccessToken).where(
                AccessToken.digest == digest(auth["Authorization"][7:])
            )
        )
        db.delete(db.get(TokenProject, token.id))
        db.commit()
    assert client.get("/targets", headers=auth).status_code == 401


def test_local_development_is_scoped_to_legacy_project(
    projects, queue_factory, valid_target_payload
):
    client, ids, headers = projects
    tid = make_target(
        client, headers[ids[1], Role.ADMIN], valid_target_payload, "Private"
    )
    app = create_app(
        Settings(auth_mode="local", _env_file=None),
        database_engine=queue_factory.kw["bind"],
    )

    def session():
        with queue_factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    with TestClient(app) as local:
        assert local.get("/targets").json() == []
        assert local.get(f"/targets/{tid}").status_code == 404


def test_project_cli_provisions_explicit_scope(
    test_engine, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(cli, "build_engine", lambda _: test_engine)
    assert cli.main(["organization-create", "--name", "Owned org"]) == 0
    assert (
        cli.main(
            ["project-create", "--organization-id", "2", "--name", "Owned project"]
        )
        == 0
    )
    assert cli.main(["projects"]) == 0
    assert "Owned project" in capsys.readouterr().out
    output = tmp_path / "private-token"
    args = [
        "issue",
        "--name",
        "test",
        "--role",
        "admin",
        "--project-id",
        "2",
        "--output",
        str(output),
    ]
    assert cli.main(args) == 0
    with Session(test_engine) as db:
        assert authenticate(db, output.read_text().strip()).project_id == 2
    assert output.read_text().strip() not in capsys.readouterr().out
    output.unlink()
    args[args.index("--project-id") + 1] = "999"
    assert cli.main(args) == 1
    assert not output.exists()
    assert (
        cli.main(["project-create", "--organization-id", "999", "--name", "bad"]) == 1
    )
    assert cli.main(["organization-create", "--name", "\n"]) == 1


def test_project_migration_preserves_legacy_data_and_pending_jobs(migration_engine):  # noqa: F811
    with migration_engine.begin() as db:
        command.upgrade(migration_config(db), "0005_access_tokens")
    tid, rid = seed_records(migration_engine)
    with migration_engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO access_tokens (id,name,role,digest,expires_at) VALUES (1,'legacy','admin',:digest,'2099-01-01')"
            ),
            {"digest": digest("snt_" + "X" * 43)},
        )
        payload = {
            "target": {"name": "Legacy"},
            "judge_runtime": {"api_key": "FAKE", "enabled": True},
        }
        jobs = EvaluationJob.__table__
        db.execute(
            jobs.insert().values(
                run_id=rid,
                target_id=tid,
                request_digest="fake",
                payload=payload,
                deadline=time.time() + 100,
            )
        )
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        assert db.get(TargetApplication, tid).project_id == 1
        assert db.get(EvaluationRun, rid).results[0].response == "FAKE_CANARY"
        assert authenticate(db, "snt_" + "X" * 43).project_id == 1
        job = db.get(EvaluationJob, rid)
        assert job.payload["target"]["project_id"] == 1
        assert job.payload["judge_runtime"]["api_key"] == "FAKE"
        assert (
            job.payload["judge_runtime"]["project_namespace"]
            == db.get(Project, 1).cache_namespace
        )
        with pytest.raises(IntegrityError):
            db.add(TargetProject(target_id=999, project_id=1))
            db.commit()
        db.rollback()
    with migration_engine.begin() as db:
        command.downgrade(migration_config(db), "0005_access_tokens")
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        assert db.get(TargetApplication, tid).project_id == 1
        assert db.get(EvaluationRun, rid).results[0].response == "FAKE_CANARY"
        db.add(Project(name="New", organization_id=1))
        db.commit()
    with pytest.raises(RuntimeError, match="Cannot downgrade multiple projects"):
        with migration_engine.begin() as db:
            command.downgrade(migration_config(db), "0005_access_tokens")


def test_judgment_cache_is_partitioned_by_project(tmp_path):
    from test_judges import run_judge, settings, successful

    from app.judges.runtime import settings_snapshot

    runtime = settings_snapshot(settings(tmp_path))
    with patch(
        "app.judges.runtime.call_provider", return_value=successful()
    ) as provider:
        first = run_judge({**runtime, "project_namespace": "project-a"})
        second = run_judge({**runtime, "project_namespace": "project-b"})
        again = run_judge({**runtime, "project_namespace": "project-a"})
    assert not first.evidence["cache_hit"] and not second.evidence["cache_hit"]
    assert again.evidence["cache_hit"] and provider.call_count == 2


def test_real_worker_keeps_project_and_judge_scope(
    projects, queue_factory, valid_target_payload, owned_provider, tmp_path
):
    from test_judges import judge_pack, settings

    from app.worker import execute_claim

    client, ids, headers = projects
    for pid in ids[:2]:
        tid = make_target(
            client,
            headers[pid, Role.ADMIN],
            {
                **valid_target_payload,
                "endpoint_url": owned_provider["target_endpoint"],
                "api_key": "FAKE_KEY",
                "request_template": {"message": ""},
                "prompt_field": "message",
                "response_field": "response",
            },
            f"Worker {pid}",
        )
        with queue_factory() as db:
            db.info["project_id"] = pid
            service = JobService(db, settings(tmp_path))
            service.evaluations.judge_runtime["endpoint"] = owned_provider["endpoint"]
            run = service.submit(tid, attack_pack=judge_pack())
            rid = run.id
        with queue_factory() as db:
            service = JobService(db)
            claim = service.claim(now=time.time() + 1)
            assert claim.payload["target"]["project_id"] == pid
            assert (
                claim.payload["judge_runtime"]["project_namespace"]
                == db.get(Project, pid).cache_namespace
            )

            def active():
                with queue_factory() as verification:
                    return JobService(verification).active(claim)

            data, retryable = execute_claim(claim, active)
            assert not retryable and data["outcome_code"] == "passed"
            assert service.finish(claim, data)
        other = ids[1] if pid == ids[0] else ids[0]
        assert (
            client.get(
                f"/evaluations/{rid}", headers=headers[other, Role.ADMIN]
            ).status_code
            == 404
        )
        evidence = client.get(
            f"/evaluations/{rid}/results", headers=headers[pid, Role.READER]
        ).text
        assert "FAKE_KEY" not in evidence and "FAKE_JUDGE_KEY" not in evidence
    assert len(owned_provider["requests"]) == 2
