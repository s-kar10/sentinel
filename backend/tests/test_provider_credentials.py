"""Synthetic project provider lifecycle, isolation, frozen work and audit contracts."""

# Imported pytest fixtures are intentionally named in signatures.
# ruff: noqa: F811

import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_jobs import queue_factory, target  # noqa: F401
from test_judges import judge_pack, owned_provider, settings  # noqa: F401
from test_migrations import migration_engine, seed_records  # noqa: F401
from test_projects import make_target, projects  # noqa: F401

from app.auth.tokens import Role
from app.core.config import get_settings
from app.database.migrations import migrate, migration_config
from app.judges.runtime import public_policy, settings_snapshot
from app.models import EvaluationRun, TargetApplication
from app.models.credential import CredentialAudit, ProviderCredential
from app.models.job import EvaluationJob
from app.models.project import Project
from app.secrets import provider_cli
from app.secrets.cli import main as key_cli
from app.secrets.cli import rewrite
from app.secrets.codec import Keyring, SecretStorageError
from app.secrets.providers import put, resolve, revoke
from app.services.errors import InvalidTargetConfigurationError
from app.services.job_service import JobService
from app.worker import execute_claim


def token_settings(tmp_path):
    config = settings(tmp_path)
    config.auth_mode = "token"
    return config


def audit(db):
    return list(db.scalars(select(CredentialAudit).order_by(CredentialAudit.id)))


def test_token_api_uses_only_own_project_and_audits_actor(
    projects, queue_factory, valid_target_payload
):
    client, ids, headers = projects
    config = client.app.state.settings
    config.judge_enabled = True
    config.judge_model = "owned-test-model"
    config.openai_api_key = SecretStr("FAKE_AMBIENT_KEY")
    tids = [
        make_target(
            client, headers[pid, Role.ADMIN], valid_target_payload, f"Project {pid}"
        )
        for pid in ids
    ]
    body = {"attack_pack": judge_pack().model_dump(mode="json")}
    with queue_factory() as db:
        put(db, ids[0], "FAKE_PROJECT_ONE")
        db.commit()
    for pid, tid in zip(ids, tids):
        response = client.post(
            f"/targets/{tid}/evaluation-jobs",
            headers={**headers[pid, Role.RUNNER], "Idempotency-Key": "same"},
            json=body,
        )
        assert response.status_code == (202 if pid == ids[0] else 422)
        assert all(
            key not in response.text
            for key in (
                "FAKE_AMBIENT_KEY",
                "FAKE_PROJECT_ONE",
                "credential_id",
                "credential_version",
            )
        )
        if pid == ids[0]:
            rid = response.json()["id"]
    assert (
        client.post(
            f"/targets/{tids[0]}/evaluation-jobs",
            headers=headers[ids[0], Role.READER],
            json=body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/targets/{tids[0]}/evaluation-jobs",
            headers=headers[ids[1], Role.ADMIN],
            json=body,
        ).status_code
        == 404
    )
    with queue_factory() as db:
        saved = db.get(EvaluationJob, rid).payload["judge_runtime"]
        assert saved["api_key"] == "FAKE_PROJECT_ONE"
        assert saved["credential_project_id"] == ids[0]
        rows = audit(db)
        assert [r.event for r in rows] == ["created", "snapshotted"]
        assert rows[-1].actor_kind == "operator" and rows[-1].token_id is not None
        assert rows[-1].run_id == rid and rows[-1].credential_version == 1
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 1
        revoke(db, ids[0])
        db.commit()
    # Retry refers to already accepted work; revocation does not admit a new run.
    assert (
        client.post(
            f"/targets/{tids[0]}/evaluation-jobs",
            headers={**headers[ids[0], Role.RUNNER], "Idempotency-Key": "same"},
            json=body,
        ).json()["id"]
        == rid
    )
    assert (
        client.post(
            f"/targets/{tids[0]}/evaluation-jobs",
            headers=headers[ids[0], Role.RUNNER],
            json=body,
        ).status_code
        == 422
    )
    client.delete(f"/targets/{tids[0]}", headers=headers[ids[0], Role.ADMIN])
    with queue_factory() as db:
        assert [r.event for r in audit(db)] == ["created", "snapshotted", "revoked"]


def test_local_fallback_is_legacy_only_and_revocation_never_falls_back(
    queue_factory, tmp_path
):
    runtime = settings_snapshot(settings(tmp_path))
    assert settings_snapshot(token_settings(tmp_path))["api_key"] == ""
    with queue_factory() as db:
        db.add(Project(name="Sibling", organization_id=1))
        db.commit()
        assert (
            resolve(db, 1, runtime, auth_mode="local")["credential_source"]
            == "legacy_environment"
        )
        for pid, mode in ((1, "token"), (2, "local"), (2, "token")):
            with pytest.raises(InvalidTargetConfigurationError):
                resolve(db, pid, runtime, auth_mode=mode)
        put(db, 1, "FAKE_LOCAL_PROJECT")
        assert (
            resolve(db, 1, runtime, auth_mode="local")["api_key"]
            == "FAKE_LOCAL_PROJECT"
        )
        revoke(db, 1)
        with pytest.raises(InvalidTargetConfigurationError, match="revoked"):
            resolve(db, 1, runtime, auth_mode="local")


def test_real_worker_keeps_frozen_key_after_replace_revoke_and_logs_dispatch(
    queue_factory, tmp_path, owned_provider
):
    tid = target(queue_factory)
    with queue_factory() as db:
        db.get(TargetApplication, tid).endpoint_url = owned_provider["target_endpoint"]
        put(db, 1, "FAKE_ORIGINAL_PROVIDER")
        db.commit()
        service = JobService(db, token_settings(tmp_path))
        service.evaluations.judge_runtime["endpoint"] = owned_provider["endpoint"]
        run = service.submit(tid, attack_pack=judge_pack(), idempotency_key="frozen")
        rid = run.id
        put(db, 1, "FAKE_REPLACEMENT_PROVIDER")
        revoke(db, 1)
        db.commit()
    with queue_factory() as db:
        service = JobService(db)
        claim = service.claim(now=time.time())
        assert claim.payload["judge_runtime"]["api_key"] == "FAKE_ORIGINAL_PROVIDER"
        assert claim.payload["judge_runtime"]["credential_version"] == 1
        data, retryable = execute_claim(claim, lambda: True)
        assert service.finish(claim, data, retryable=retryable)
        assert db.get(EvaluationJob, rid).payload is None
        rows = audit(db)
        assert [r.event for r in rows] == [
            "created",
            "snapshotted",
            "replaced",
            "revoked",
            "dispatched",
        ]
        assert rows[-1].actor_kind == "worker" and rows[-1].token_id is None
        assert rows[-1].credential_version == 1
    assert owned_provider["requests"][-1][2] == "Bearer FAKE_ORIGINAL_PROVIDER"


def test_service_reuse_cannot_carry_credential_to_another_project(
    queue_factory, tmp_path
):
    first = target(queue_factory)
    second = target(queue_factory)
    with queue_factory() as db:
        sibling = Project(name="Sibling", organization_id=1)
        db.add(sibling)
        db.flush()
        db.get(TargetApplication, second).ownership.project_id = sibling.id
        put(db, 1, "FAKE_FIRST")
        db.commit()
        service = JobService(db, settings(tmp_path))
        service.submit(first, attack_pack=judge_pack())
        with pytest.raises(InvalidTargetConfigurationError):
            service.submit(second, attack_pack=judge_pack())


def test_concurrent_provisioning_serializes_versions_and_audit(queue_factory):
    def provision(index):
        with queue_factory() as db, db.begin():
            row = put(db, 1, f"FAKE_VERSION_{index}")
            return row.id, row.version

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(provision, range(4)))
    assert len({identifier for identifier, _ in results}) == 1
    assert sorted(version for _, version in results) == [1, 2, 3, 4]
    with queue_factory() as db:
        assert [r.credential_version for r in audit(db)] == [1, 2, 3, 4]


def test_audit_failure_rolls_back_submission_and_provisioning(queue_factory, tmp_path):
    tid = target(queue_factory)
    with queue_factory() as db:
        with patch(
            "app.secrets.providers.record",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with pytest.raises(RuntimeError), db.begin():
                put(db, 1, "FAKE_ROLLED_BACK")
        assert db.scalar(select(func.count()).select_from(ProviderCredential)) == 0
        db.rollback()
        put(db, 1, "FAKE_ACTIVE")
        db.commit()
        service = JobService(db, token_settings(tmp_path))
        with patch(
            "app.services.evaluation_service.record",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with pytest.raises(RuntimeError):
                service.submit(tid, attack_pack=judge_pack())
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 0
        assert db.scalar(select(func.count()).select_from(EvaluationJob)) == 0
        assert len(audit(db)) == 1


def test_cli_private_input_metadata_pagination_and_revocation(
    queue_factory, tmp_path, monkeypatch, capsys
):
    engine = queue_factory.kw["bind"]
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.delenv("DATABASE_HOST", raising=False)
    get_settings.cache_clear()
    source = tmp_path / "provider.txt"
    source.write_text("FAKE_PRIVATE_PROVIDER\n")
    source.chmod(0o600)
    args = ["put", "--project-id", "1", "--input-file", str(source)]
    assert provider_cli.main(args) == 0
    assert provider_cli.main(args) == 0
    for command_name in ("list", "audit"):
        assert provider_cli.main([command_name, "--project-id", "1"]) == 0
    assert (
        provider_cli.main(
            ["audit", "--project-id", "1", "--after-id", "1", "--limit", "1"]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "FAKE_PRIVATE_PROVIDER" not in output
    assert '"version": 2' in output and '"actor_kind": "host_cli"' in output
    assert json.loads(output.splitlines()[-1])[0]["id"] == 2
    source.chmod(0o644)
    assert provider_cli.main(args) == 1
    assert (
        provider_cli.main(["put", "--project-id", "999", "--input-file", str(source)])
        == 1
    )
    with engine.connect() as conn:
        stored = conn.scalar(text("SELECT secret FROM provider_credentials"))
        assert stored.startswith("sntenc1:") and "FAKE_PRIVATE_PROVIDER" not in stored
    # Metadata and local revocation do not require decrypting the old credential.
    with engine.begin() as conn:
        conn.execute(text("UPDATE provider_credentials SET secret='INVALID'"))
    assert provider_cli.main(["list", "--project-id", "1"]) == 0
    assert provider_cli.main(["revoke", "--project-id", "1"]) == 0
    assert provider_cli.main(["revoke", "--project-id", "1"]) == 0
    with queue_factory() as db:
        assert db.scalar(select(ProviderCredential.secret)) is None
        assert [r.event for r in audit(db)] == ["created", "replaced", "revoked"]


def test_provider_ciphertext_is_separate_and_key_rotation_covers_it(
    queue_factory, private_keyring, tmp_path
):
    engine = queue_factory.kw["bind"]
    with queue_factory() as db:
        put(db, 1, "FAKE_PROVIDER")
        db.commit()
    with engine.connect() as conn:
        ciphertext = conn.scalar(text("SELECT secret FROM provider_credentials"))
    with pytest.raises(SecretStorageError):
        Keyring(str(private_keyring)).open(ciphertext, "target-api-key")
    next_path = tmp_path / "rotated.json"
    assert (
        key_cli(
            ["add-key", "--source", str(private_keyring), "--output", str(next_path)]
        )
        == 0
    )
    with engine.begin() as conn:
        assert rewrite(conn, Keyring(str(next_path)))["provider_credentials"] == 1
    with engine.connect() as conn:
        new_ciphertext = conn.scalar(text("SELECT secret FROM provider_credentials"))
    keys = json.loads(next_path.read_text())
    keys["keys"] = {keys["active"]: keys["keys"][keys["active"]]}
    next_path.write_text(json.dumps(keys))
    assert (
        Keyring(str(next_path)).open(new_ciphertext, "provider-api-key")
        == "FAKE_PROVIDER"
    )


def test_migration_preserves_existing_keys_and_refuses_audit_loss(migration_engine):
    with migration_engine.begin() as conn:
        command.upgrade(migration_config(conn), "0007_encrypted_credentials")
    tid, _ = seed_records(migration_engine)
    with migration_engine.connect() as conn:
        before = conn.scalar(text("SELECT api_key FROM target_applications"))
    migrate(migration_engine, "upgrade")
    with migration_engine.connect() as conn:
        assert conn.scalar(text("SELECT api_key FROM target_applications")) == before
        assert conn.scalar(text("SELECT count(*) FROM provider_credentials")) == 0
    with Session(migration_engine) as db:
        assert db.get(TargetApplication, tid).api_key == "FAKE_MIGRATION_KEY"
        put(db, 1, "FAKE_MIGRATION_PROVIDER")
        revoke(db, 1)
        db.commit()
    with pytest.raises(RuntimeError, match="audit history"):
        with migration_engine.begin() as conn:
            command.downgrade(migration_config(conn), "0007_encrypted_credentials")


def test_provider_metadata_is_private_and_unknown_input_rejected(
    queue_factory, tmp_path
):
    with queue_factory() as db:
        for value in ("", "FAKE KEY", "FAKE\nKEY", "FAKE\x00KEY", "☃", "x" * 4097):
            with pytest.raises(ValueError):
                put(db, 1, value)
        assert not audit(db)
        row = put(db, 1, "FAKE_SAFE")
        runtime = resolve(
            db, 1, settings_snapshot(token_settings(tmp_path)), auth_mode="token"
        )
        assert runtime["credential_id"] == row.id
        assert not any(
            name.startswith("credential_") for name in public_policy(runtime)
        )


def test_revoke_and_submission_have_one_serial_order(queue_factory, tmp_path):
    from threading import Barrier

    tid = target(queue_factory)
    with queue_factory() as db:
        put(db, 1, "FAKE_RACE_KEY")
        db.commit()
    ready = Barrier(2)

    def submit_job():
        with queue_factory() as db:
            ready.wait()
            try:
                return (
                    JobService(db, token_settings(tmp_path))
                    .submit(tid, attack_pack=judge_pack())
                    .id
                )
            except InvalidTargetConfigurationError:
                return None

    def revoke_key():
        with queue_factory() as db, db.begin():
            ready.wait()
            return revoke(db, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        submission = pool.submit(submit_job)
        revocation = pool.submit(revoke_key)
        rid = submission.result(timeout=15)
        assert revocation.result(timeout=15)
    with queue_factory() as db:
        events = [r.event for r in audit(db)]
        assert events == (
            ["created", "snapshotted", "revoked"] if rid else ["created", "revoked"]
        )
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == (
            1 if rid else 0
        )


def test_legacy_frozen_jobs_still_dispatch_and_fail_closed_on_new_scope_mismatch(
    queue_factory, tmp_path
):
    tid = target(queue_factory)
    with queue_factory() as db:
        service = JobService(db, settings(tmp_path))
        rid = service.submit(tid, attack_pack=judge_pack()).id
        saved = db.get(EvaluationJob, rid)
        payload = dict(saved.payload)
        payload["judge_runtime"] = {
            key: value
            for key, value in payload["judge_runtime"].items()
            if not key.startswith("credential_")
        }
        saved.payload = payload
        db.commit()
        claim = service.claim()
        assert claim is not None
        assert audit(db)[-1].source == "legacy_snapshot"
        service.cancel(rid)
        second = service.submit(tid, attack_pack=judge_pack()).id
        saved = db.get(EvaluationJob, second)
        saved.payload = {
            **saved.payload,
            "judge_runtime": {
                **saved.payload["judge_runtime"],
                "credential_project_id": 999,
            },
        }
        db.commit()
        assert service.claim(now=time.time() + 1) is None
        assert db.get(EvaluationJob, second).payload is None


def test_cli_runs_in_fresh_process_without_api_imports(
    queue_factory, private_keyring, tmp_path
):
    import os
    import subprocess
    import sys
    from pathlib import Path

    source = tmp_path / "cold-provider.txt"
    source.write_text("FAKE_COLD_CLI_KEY")
    source.chmod(0o600)
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "DATABASE_URL": queue_factory.kw["bind"].url.render_as_string(
            hide_password=False
        ),
        "SECRET_KEYRING_FILE": str(private_keyring),
    }
    for operation in ("put", "list", "revoke", "audit"):
        args = [
            sys.executable,
            "-m",
            "app.secrets.provider_cli",
            operation,
            "--project-id",
            "1",
        ]
        if operation == "put":
            args += ["--input-file", str(source)]
        completed = subprocess.run(
            args, cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15
        )
        assert completed.returncode == 0, completed.stderr
        assert "FAKE_COLD_CLI_KEY" not in completed.stdout + completed.stderr
    with queue_factory() as db:
        assert [row.event for row in audit(db)] == ["created", "revoked"]


def test_dispatch_audit_failure_does_not_admit_case(queue_factory, tmp_path):
    tid = target(queue_factory)
    with queue_factory() as db:
        put(db, 1, "FAKE_WORKER_AUDIT")
        db.commit()
        rid = (
            JobService(db, token_settings(tmp_path))
            .submit(tid, attack_pack=judge_pack())
            .id
        )
    # Match run_once's session lifetime: failed admission closes and rolls back.
    with patch(
        "app.services.job_service.record", side_effect=RuntimeError("audit unavailable")
    ):
        with pytest.raises(RuntimeError), queue_factory() as db:
            JobService(db).claim()
    with queue_factory() as db:
        job = db.get(EvaluationJob, rid)
        assert job.state == "queued" and job.token is None and job.attempts == 0
        assert [row.event for row in audit(db)] == ["created", "snapshotted"]
        assert JobService(db).claim() is not None
        assert [row.event for row in audit(db)] == [
            "created",
            "snapshotted",
            "dispatched",
        ]
