"""Synthetic credential tests: raw SQL, failure closure, migration and rotation."""

import json
import os

import pytest
from alembic import command
from sqlalchemy import JSON, MetaData, Table, text
from sqlalchemy.orm import Session
from test_jobs import queue_factory, submit, target  # noqa: F401
from test_judges import judge_pack, settings
from test_migrations import migration_engine, seed_records  # noqa: F401

from app.core.config import get_settings
from app.database.migrations import current_revisions, migrate, migration_config
from app.models import EvaluationRun, TargetApplication
from app.models.job import EvaluationJob
from app.secrets.cli import main, rewrite
from app.secrets.codec import Keyring, SecretStorageError, new_keyring, write_keyring
from app.services.job_service import JobService


def raw_payload(engine, rid):
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT payload FROM evaluation_jobs WHERE run_id=:id").columns(
                payload=JSON
            ),
            {"id": rid},
        )


def test_envelope_authentication_and_randomness(private_keyring):
    ring = Keyring(str(private_keyring))
    first = ring.seal("FAKE_SECRET", "target-api-key")
    second = ring.seal("FAKE_SECRET", "target-api-key")
    assert first != second and "FAKE_SECRET" not in first
    assert ring.open(first, "target-api-key") == "FAKE_SECRET"
    for envelope, purpose in (
        (first, "job-payload"),
        (first[:-4] + "AAAA", "target-api-key"),
        ("FAKE_SECRET", "target-api-key"),
        (first.replace("sntenc1", "sntenc2"), "target-api-key"),
    ):
        with pytest.raises(SecretStorageError) as caught:
            ring.open(envelope, purpose)
        assert "FAKE_SECRET" not in str(caught.value)
        assert envelope not in str(caught.value)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "public",
        "symlink",
        "oversized",
        "invalid",
        "short-key",
        "unknown-key",
        "directory",
        "fifo",
    ],
)
def test_keyring_rejects_unsafe_files(tmp_path, damage):
    path = tmp_path / "private.json"
    if damage == "directory":
        path.mkdir()
    elif damage == "fifo":
        os.mkfifo(path, 0o600)
    elif damage != "missing":
        value = new_keyring()
        if damage == "short-key":
            value["keys"][value["active"]] = "YQ=="
        if damage == "unknown-key":
            value["active"] = "missing"
        write_keyring(path, value)
        if damage == "public":
            path.chmod(0o644)
        if damage == "symlink":
            source = tmp_path / "source.json"
            path.rename(source)
            path.symlink_to(source)
        if damage in {"oversized", "invalid"}:
            path.write_text("x" * (20_000 if damage == "oversized" else 3))
    with pytest.raises(SecretStorageError):
        Keyring(str(path))


def test_private_cli_never_overwrites_or_prints_keys(tmp_path, capsys):
    path = tmp_path / "created-keyring.json"
    assert main(["init", "--output", str(path)]) == 0
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert main(["init", "--output", str(path)]) == 1
    assert path.read_bytes() == original
    next_path = tmp_path / "next.json"
    assert main(["add-key", "--source", str(path), "--output", str(next_path)]) == 0
    first, second = Keyring(str(path)), Keyring(str(next_path))
    assert first.active != second.active
    assert second.open(first.seal("FAKE", "test"), "test") == "FAKE"
    output = capsys.readouterr()
    for key in json.loads(original)["keys"].values():
        assert key not in output.out + output.err


def test_target_and_provider_snapshots_encrypted_and_frozen(queue_factory, tmp_path):  # noqa: F811
    tid = target(queue_factory)
    with queue_factory() as db:
        run = JobService(db, settings(tmp_path)).submit(tid, attack_pack=judge_pack())
        rid = run.id
        db.get(TargetApplication, tid).api_key = "REPLACEMENT_FAKE_KEY"
        db.commit()
    engine = queue_factory.kw["bind"]
    stored = raw_payload(engine, rid)
    assert set(stored) == {"encrypted"}
    assert not any(
        key in json.dumps(stored)
        for key in ("FAKE_KEY", "FAKE_JUDGE_KEY", "REPLACEMENT_FAKE_KEY")
    )
    with engine.connect() as connection:
        assert "REPLACEMENT_FAKE_KEY" not in connection.scalar(
            text("SELECT api_key FROM target_applications")
        )
    with queue_factory() as db:
        claim = JobService(db).claim()
        assert claim.payload["target"]["api_key"] == "FAKE_KEY"
        assert claim.payload["judge_runtime"]["api_key"] == "FAKE_JUDGE_KEY"
        JobService(db).cancel(rid)
    assert raw_payload(engine, rid) is None


def test_rotation_preserves_pending_work_and_old_key_can_be_removed(
    queue_factory,  # noqa: F811
    private_keyring,
    tmp_path,
    monkeypatch,  # noqa: F811
):
    tid = target(queue_factory)
    rid = submit(queue_factory, tid)
    engine = queue_factory.kw["bind"]
    before = raw_payload(engine, rid)
    next_path = tmp_path / "next.json"
    assert (
        main(["add-key", "--source", str(private_keyring), "--output", str(next_path)])
        == 0
    )
    ring = Keyring(str(next_path))
    with engine.begin() as connection:
        assert rewrite(connection, ring) == {
            "target_applications": 1,
            "evaluation_jobs": 1,
        }
    assert raw_payload(engine, rid) != before
    # Removing an old key before rotation would fail; after rotation all live rows work.
    only_new = json.loads(next_path.read_text())
    only_new["keys"] = {only_new["active"]: only_new["keys"][only_new["active"]]}
    next_path.write_text(json.dumps(only_new))
    monkeypatch.setenv("SECRET_KEYRING_FILE", str(next_path))
    get_settings.cache_clear()
    with engine.begin() as connection:
        rewrite(connection, Keyring(str(next_path)), verify_only=True)
    with queue_factory() as db:
        assert db.get(TargetApplication, tid).api_key == "FAKE_KEY"
        assert JobService(db).claim().payload["target"]["api_key"] == "FAKE_KEY"
    with pytest.raises(SecretStorageError):
        Keyring(str(next_path)).open(before["encrypted"], "job-payload")


def test_rotation_rolls_back_if_any_ciphertext_is_invalid(
    queue_factory,  # noqa: F811
    private_keyring,  # noqa: F811
):
    tid = target(queue_factory)
    rid = submit(queue_factory, tid)
    engine = queue_factory.kw["bind"]
    with engine.begin() as connection:
        before = connection.scalar(text("SELECT api_key FROM target_applications"))
        jobs = Table("evaluation_jobs", MetaData(), autoload_with=connection)
        connection.execute(
            jobs.update()
            .where(jobs.c.run_id == rid)
            .values(payload={"encrypted": "broken"})
        )
    with pytest.raises(SecretStorageError):
        with engine.begin() as connection:
            rewrite(connection, Keyring(str(private_keyring)))
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT api_key FROM target_applications")) == before
        )


def test_missing_key_and_plaintext_are_sanitized_api_failures(
    api_client, valid_target_payload, private_keyring, test_engine
):
    created = api_client.post("/targets", json=valid_target_payload).json()
    with test_engine.begin() as connection:
        connection.execute(
            text("UPDATE target_applications SET api_key='FAKE_UNENCRYPTED'")
        )
    response = api_client.get(f"/targets/{created['id']}")
    assert response.status_code == 503
    assert "FAKE_UNENCRYPTED" not in response.text
    private_keyring.unlink()
    assert api_client.get("/ready").status_code == 503
    assert api_client.get("/health").status_code == 200
    response = api_client.post("/targets", json=valid_target_payload)
    assert response.status_code == 503
    assert "fake-test-key" not in response.text
    with test_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM target_applications")) == 1


def test_legacy_migration_is_atomic_and_preserves_frozen_credentials(
    migration_engine,  # noqa: F811
    private_keyring,  # noqa: F811
):
    with migration_engine.begin() as connection:
        command.upgrade(migration_config(connection), "0006_projects")
    tid, rid = seed_records(migration_engine)
    payload = {
        "target": {"id": tid, "project_id": 1, "api_key": "FAKE_TARGET"},
        "judge_runtime": {"api_key": "FAKE_PROVIDER"},
        "protected_values": ["FAKE_CANARY"],
    }
    with migration_engine.begin() as connection:
        jobs = Table("evaluation_jobs", MetaData(), autoload_with=connection)
        connection.execute(
            jobs.insert().values(
                run_id=rid,
                target_id=tid,
                request_digest="test",
                payload=payload,
                cursor=0,
                attempts=0,
                available_at=0,
                deadline=100,
                lease_until=0,
                state="queued",
            )
        )
    key_bytes = private_keyring.read_bytes()
    private_keyring.unlink()
    with pytest.raises(SecretStorageError):
        migrate(migration_engine, "upgrade")
    with migration_engine.connect() as connection:
        assert current_revisions(connection) == ("0006_projects",)
        assert (
            connection.scalar(text("SELECT api_key FROM target_applications"))
            == "FAKE_MIGRATION_KEY"
        )
    private_keyring.write_bytes(key_bytes)
    private_keyring.chmod(0o600)
    migrate(migration_engine, "upgrade")
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        assert db.get(TargetApplication, tid).api_key == "FAKE_MIGRATION_KEY"
        assert db.get(EvaluationJob, rid).payload == payload
        assert db.get(EvaluationRun, rid).results[0].response == "FAKE_CANARY"
    with migration_engine.connect() as connection:
        assert "FAKE_MIGRATION_KEY" not in connection.scalar(
            text("SELECT api_key FROM target_applications")
        )
    assert "FAKE_PROVIDER" not in json.dumps(raw_payload(migration_engine, rid))
    with pytest.raises(RuntimeError, match="Cannot downgrade encrypted"):
        with migration_engine.begin() as connection:
            command.downgrade(migration_config(connection), "0006_projects")


def test_database_cli_verifies_and_reencrypts_without_printing_secrets(
    queue_factory,  # noqa: F811
    monkeypatch,
    capsys,
):
    tid = target(queue_factory)
    rid = submit(queue_factory, tid)
    engine = queue_factory.kw["bind"]
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.delenv("DATABASE_HOST", raising=False)
    get_settings.cache_clear()
    before = raw_payload(engine, rid)
    assert main(["verify"]) == 0
    assert raw_payload(engine, rid) == before
    assert main(["reencrypt"]) == 0
    assert raw_payload(engine, rid) != before
    assert main(["verify"]) == 0
    output = capsys.readouterr()
    assert "FAKE_KEY" not in output.out + output.err
    assert '"target_applications": 1' in output.out
    assert '"evaluation_jobs": 1' in output.out
