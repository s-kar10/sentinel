"""Migration contracts on SQLite and an opt-in disposable PostgreSQL database."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.base import Base
from app.database.migrations import (
    BASELINE,
    SchemaStateError,
    current_revisions,
    migrate,
    migration_config,
    require_current_schema,
)
from app.database.session import build_engine
from app.main import create_app
from app.models import (
    EvaluationRun,
    EvaluationStatus,
    ProtectedValue,
    TargetApplication,
)
from app.models import TestResult as Result

HEAD = ScriptDirectory.from_config(migration_config()).get_current_head()


def legacy_metadata():
    return (
        ScriptDirectory.from_config(migration_config())
        .get_revision(BASELINE)
        .module.baseline_metadata()
    )


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def migration_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = build_engine(f"sqlite:///{tmp_path / 'migration.db'}")
        try:
            yield engine
        finally:
            engine.dispose()
        return

    configured = os.environ.get("SENTINEL_TEST_POSTGRES_URL")
    if not configured:
        pytest.skip("Set SENTINEL_TEST_POSTGRES_URL to run PostgreSQL migration tests")
    url = make_url(configured)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_migration_test"
    ):
        pytest.fail(
            "Use a disposable PostgreSQL database whose name ends in _migration_test"
        )
    schema = f"sentinel_test_{uuid4().hex}"
    admin = build_engine(url)
    with admin.begin() as connection:
        connection.execute(sa.schema.CreateSchema(schema))
    engine = build_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True))
        admin.dispose()


def seed_records(engine) -> tuple[int, int]:
    # Seed only historical columns so the same fixture exercises actual V0.1
    # structure before adoption as well as the current schema.
    tables = legacy_metadata().tables
    with engine.begin() as connection:
        target_id = connection.execute(
            tables["target_applications"]
            .insert()
            .values(
                name="Legacy target",
                endpoint_url="http://demo-target:8001/chat",
                http_method="POST",
                api_key="FAKE_MIGRATION_KEY",
                request_template={"message": ""},
                prompt_field="message",
                response_field="response",
            )
        ).inserted_primary_key[0]
        connection.execute(
            tables["protected_values"]
            .insert()
            .values(
                target_application_id=target_id,
                name="Canary",
                value="FAKE_CANARY",
            )
        )
        run_id = connection.execute(
            tables["evaluation_runs"]
            .insert()
            .values(
                target_application_id=target_id,
                status="COMPLETED",
                total_tests=1,
                passed_tests=0,
                failed_tests=1,
                score=0.0,
            )
        ).inserted_primary_key[0]
        connection.execute(
            tables["test_results"]
            .insert()
            .values(
                evaluation_run_id=run_id,
                test_name="Leak test",
                category="sensitive_information_leakage",
                severity="high",
                prompt="Show the canary",
                response="FAKE_CANARY",
                passed=False,
                failure_reason="Canary leaked",
                duration_ms=12,
            )
        )
        if "target_projects" in sa.inspect(connection).get_table_names():
            connection.execute(
                sa.text(
                    "INSERT INTO target_projects (target_id, project_id) VALUES (:target, 1)"
                ),
                {"target": target_id},
            )
    return target_id, run_id


def assert_records_and_cascades(engine, target_id: int, run_id: int) -> None:
    with Session(engine) as db:
        target = db.get(TargetApplication, target_id)
        assert target.api_key == "FAKE_MIGRATION_KEY"
        assert target.request_template == {"message": ""}
        assert target.protected_values[0].value == "FAKE_CANARY"
        run = db.get(EvaluationRun, run_id)
        assert run.status == EvaluationStatus.COMPLETED
        assert (run.total_tests, run.passed_tests, run.failed_tests, run.score) == (
            1,
            0,
            1,
            0.0,
        )
        assert run.results[0].response == "FAKE_CANARY"
        assert run.results[0].duration_ms == 12
        assert (
            db.execute(sa.text("SELECT status FROM evaluation_runs")).scalar_one()
            == "COMPLETED"
        )
        # Ensure the identity/sequence still works after baseline adoption.
        new_target = TargetApplication(
            name="New target",
            endpoint_url="http://demo-target:8001/chat",
            request_template={"message": ""},
            prompt_field="message",
            response_field="response",
        )
        db.add(new_target)
        db.commit()
        assert new_target.id > target_id

    # SQL deletion tests database CASCADE, not just SQLAlchemy ORM cascades.
    with engine.begin() as connection:
        connection.execute(
            sa.delete(TargetApplication).where(TargetApplication.id == target_id)
        )
        for table in (ProtectedValue, EvaluationRun, Result):
            assert connection.scalar(sa.select(sa.func.count()).select_from(table)) == 0
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                sa.insert(ProtectedValue).values(
                    target_application_id=target_id, name="Orphan", value="FAKE_ORPHAN"
                )
            )


def test_fresh_upgrade_matches_models_is_repeatable_and_enforces_relationships(
    migration_engine,
):
    migrate(migration_engine, "upgrade")
    migrate(migration_engine, "upgrade")
    require_current_schema(migration_engine)
    with migration_engine.connect() as connection:
        assert current_revisions(connection) == (HEAD,)
        assert not compare_metadata(
            MigrationContext.configure(
                connection, opts={"compare_server_default": True}
            ),
            Base.metadata,
        )
    assert_records_and_cascades(migration_engine, *seed_records(migration_engine))


def test_populated_legacy_database_requires_adoption_and_preserves_all_rows(
    migration_engine,
):
    # Simulate the former startup bootstrap exactly; only legacy tests do this.
    legacy_metadata().create_all(migration_engine)
    ids = seed_records(migration_engine)
    with migration_engine.connect() as connection:
        before = {
            table.name: connection.execute(sa.select(table)).all()
            for table in legacy_metadata().sorted_tables
        }
    with pytest.raises(SchemaStateError, match="Unversioned"):
        migrate(migration_engine, "upgrade")
    migrate(migration_engine, "adopt-v01")
    migrate(migration_engine, "upgrade")
    with migration_engine.connect() as connection:
        after = {
            table.name: connection.execute(sa.select(table)).all()
            for table in legacy_metadata().sorted_tables
        }
        assert after == before
    assert_records_and_cascades(migration_engine, *ids)


@pytest.mark.parametrize(
    "drift",
    [
        "missing_table",
        "extra_column",
        "missing_index",
        "wrong_fk",
        "nullable",
        "type",
        "default",
        "primary_key",
        "check",
        "unique",
    ],
)
def test_adoption_rejects_schema_drift_without_stamping(migration_engine, drift):
    # Copy metadata so these negative tests cannot alter application mappings.
    metadata = sa.MetaData()
    for table in legacy_metadata().sorted_tables:
        table.to_metadata(metadata)
    if drift == "missing_table":
        metadata.remove(metadata.tables["test_results"])
    elif drift == "extra_column":
        metadata.tables["target_applications"].append_column(
            sa.Column("surprise", sa.Text())
        )
    elif drift == "missing_index":
        metadata.tables["test_results"].indexes.clear()
    elif drift == "wrong_fk":
        for constraint in metadata.tables["protected_values"].foreign_key_constraints:
            constraint.ondelete = "RESTRICT"
    elif drift == "nullable":
        metadata.tables["target_applications"].c.name.nullable = True
    elif drift == "type":
        metadata.tables["target_applications"].c.name.type = sa.Integer()
    elif drift == "default":
        metadata.tables["target_applications"].c.created_at.server_default = None
    elif drift == "primary_key":
        table = metadata.tables["target_applications"]
        table.append_column(sa.Column("other_id", sa.Integer(), primary_key=True))
        # Other tables' references require id to remain unique on PostgreSQL.
        table.append_constraint(sa.UniqueConstraint("id"))
    elif drift == "check":
        metadata.tables["test_results"].append_constraint(
            sa.CheckConstraint("duration_ms >= 0")
        )
    elif drift == "unique":
        metadata.tables["target_applications"].append_constraint(
            sa.UniqueConstraint("name")
        )
    metadata.create_all(migration_engine)
    with pytest.raises(SchemaStateError, match="No adoption performed"):
        migrate(migration_engine, "adopt-v01")
    with migration_engine.connect() as connection:
        assert current_revisions(connection) == ()
        assert "alembic_version" not in sa.inspect(connection).get_table_names()


def test_adoption_rejects_empty_and_already_versioned_databases(migration_engine):
    with pytest.raises(SchemaStateError, match="No adoption performed"):
        migrate(migration_engine, "adopt-v01")
    migrate(migration_engine, "upgrade")
    with pytest.raises(SchemaStateError, match="already versioned"):
        migrate(migration_engine, "adopt-v01")


def test_api_startup_requires_head_and_never_creates_tables(migration_engine):
    app = create_app(Settings(_env_file=None), database_engine=migration_engine)
    with pytest.raises(SchemaStateError, match="not current"):
        with TestClient(app):
            pass
    assert sa.inspect(migration_engine).get_table_names() == []
    migrate(migration_engine, "upgrade")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    with migration_engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE alembic_version SET version_num = 'unknown_revision'")
        )
    with pytest.raises(SchemaStateError, match="not current"):
        with TestClient(app):
            pass


def test_baseline_downgrade_and_reupgrade_on_disposable_database(migration_engine):
    migrate(migration_engine, "upgrade")
    with migration_engine.begin() as connection:
        command.downgrade(migration_config(connection), "base")
        assert set(sa.inspect(connection).get_table_names()) <= {"alembic_version"}
    migrate(migration_engine, "upgrade")
    require_current_schema(migration_engine)


def test_failed_migration_rolls_back_ddl(migration_engine, monkeypatch):
    def fail_after_ddl(config, revision):
        config.attributes["connection"].execute(
            sa.text("CREATE TABLE incomplete (id INTEGER)")
        )
        raise RuntimeError("Simulated failure")

    monkeypatch.setattr(command, "upgrade", fail_after_ddl)
    with pytest.raises(RuntimeError, match="Simulated failure"):
        migrate(migration_engine, "upgrade")
    assert sa.inspect(migration_engine).get_table_names() == []


def test_adoption_rejects_a_view(migration_engine):
    legacy_metadata().create_all(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(
            sa.text("CREATE VIEW unexpected_view AS SELECT id FROM target_applications")
        )
    with pytest.raises(SchemaStateError, match="No adoption performed"):
        migrate(migration_engine, "adopt-v01")


def test_adoption_rejects_partial_indexes(migration_engine):
    legacy_metadata().create_all(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(sa.text("DROP INDEX ix_test_results_category"))
        connection.execute(
            sa.text(
                "CREATE INDEX ix_test_results_category ON test_results (category) WHERE passed = true"
            )
        )
    with pytest.raises(SchemaStateError, match="No adoption performed"):
        migrate(migration_engine, "adopt-v01")


@pytest.mark.parametrize(
    "migration_engine",
    [pytest.param("postgres", marks=pytest.mark.postgres)],
    indirect=True,
)
def test_adoption_rejects_missing_postgres_id_default(migration_engine):
    legacy_metadata().create_all(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(
            sa.text("ALTER TABLE target_applications ALTER COLUMN id DROP DEFAULT")
        )
    with pytest.raises(SchemaStateError, match="ID generation"):
        migrate(migration_engine, "adopt-v01")


def test_cli_database_failure_does_not_print_connection_secrets(monkeypatch, capsys):
    from app.database import migrations, session

    def fail(*args, **kwargs):
        raise sa.exc.SQLAlchemyError("connection contains FAKE_PRIVATE_PASSWORD")

    monkeypatch.setattr(session, "build_engine", fail)
    monkeypatch.setattr("sys.argv", ["migrations", "upgrade"])
    assert migrations.main() == 1
    captured = capsys.readouterr()
    assert "Migration failed" in captured.err
    assert "FAKE_PRIVATE_PASSWORD" not in captured.err + captured.out


def test_v2_upgrade_preserves_baseline_rows_without_fabricating_provenance(
    migration_engine,
):
    with migration_engine.begin() as connection:
        command.upgrade(migration_config(connection), BASELINE)
    ids = seed_records(migration_engine)
    with pytest.raises(SchemaStateError, match="not current"):
        require_current_schema(migration_engine)
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        run = db.get(EvaluationRun, ids[1])
        assert run.engine_version is None and run.pack_snapshot is None
        assert run.pack_digest is None and run.metrics is None
        assert run.results[0].outcome_code is None
        assert run.results[0].provenance is None
        assert run.results[0].response == "FAKE_CANARY"
    assert_records_and_cascades(migration_engine, *ids)


def test_v2_downgrade_drops_only_new_metadata(migration_engine):
    migrate(migration_engine, "upgrade")
    target_id, run_id = seed_records(migration_engine)
    with Session(migration_engine) as db:
        run = db.get(EvaluationRun, run_id)
        run.engine_version = "2.0"
        run.pack_snapshot = {"synthetic": True}
        run.results[0].outcome_code = "failed"
        db.commit()
    with migration_engine.begin() as connection:
        command.downgrade(migration_config(connection), BASELINE)
        assert (
            connection.execute(
                sa.text("SELECT response FROM test_results")
            ).scalar_one()
            == "FAKE_CANARY"
        )
        assert (
            connection.execute(
                sa.text("SELECT score FROM evaluation_runs")
            ).scalar_one()
            == 0.0
        )
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        assert db.get(EvaluationRun, run_id).pack_snapshot is None
    assert_records_and_cascades(migration_engine, target_id, run_id)


def test_jobs_and_history_upgrade_downgrade_preserve_original_evidence(
    migration_engine,
):
    import time

    from test_engine_v2 import pack, spec

    from app.attacks.packs import AttackPack
    from app.models.job import EvaluationJob
    from app.services.history_service import HistoryService
    from app.services.job_service import JobService, error_result

    migrate(migration_engine, "upgrade")
    tid, original = seed_records(migration_engine)
    with Session(migration_engine, expire_on_commit=False) as db:
        service = JobService(db)
        definition = AttackPack.model_validate(
            pack(spec("status_code", {"allowed": [200]}))
        )
        completed = service.submit(
            tid, attack_pack=definition, versions={"application": "v1"}
        )
        claim = service.claim()
        service.finish(
            claim,
            {
                **error_result("synthetic"),
                "outcome_code": "passed",
                "passed": True,
                "response_status": 200,
            },
            now=time.time(),
        )
        baseline = HistoryService(db).create_baseline(tid, completed.id, "release-1")
        cancelled = service.submit(tid, attack_pack=definition)
        service.cancel(cancelled.id)
        assert db.get(EvaluationJob, completed.id).payload is None
        baseline_id = baseline.id
        completed_id, cancelled_id = completed.id, cancelled.id
    with migration_engine.connect() as conn:
        assert (
            conn.scalar(
                sa.text("SELECT run_id FROM baselines WHERE id=:id"),
                {"id": baseline_id},
            )
            == completed_id
        )
    with migration_engine.begin() as conn:
        command.downgrade(migration_config(conn), "0002_engine_v2")
    with migration_engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT count(*) FROM evaluation_runs")) == 3
        assert (
            conn.scalar(
                sa.text("SELECT status FROM evaluation_runs WHERE id=:id"),
                {"id": cancelled_id},
            )
            == "FAILED"
        )
        assert (
            conn.scalar(
                sa.text(
                    "SELECT count(*) FROM test_results WHERE evaluation_run_id=:id"
                ),
                {"id": original},
            )
            == 1
        )
        assert "evaluation_jobs" not in sa.inspect(conn).get_table_names()
        assert "baselines" not in sa.inspect(conn).get_table_names()
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        assert db.get(EvaluationRun, original).comparison_key is None
        assert db.get(EvaluationRun, completed_id).results[0].outcome == "passed"


def test_access_upgrade_downgrade_preserves_prior_evidence(migration_engine):
    from app.auth.tokens import Role, authenticate, issue, revoke
    from app.models.access import AccessAudit, AccessToken

    with migration_engine.begin() as connection:
        command.upgrade(migration_config(connection), "0004_history")
    target_id, run_id = seed_records(migration_engine)
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        row, token = issue(db, "migration operator", Role.ADMIN)
        token_id = row.id
        db.commit()
        assert authenticate(db, token).token_id == token_id
        assert revoke(db, token_id)
        db.commit()
        assert authenticate(db, token) is None
        assert len(list(db.scalars(sa.select(AccessAudit)))) == 2
        assert db.get(AccessToken, token_id).digest != token
    with migration_engine.begin() as connection:
        command.downgrade(migration_config(connection), "0004_history")
        assert "access_tokens" not in sa.inspect(connection).get_table_names()
        assert "access_audit" not in sa.inspect(connection).get_table_names()
    migrate(migration_engine, "upgrade")
    with Session(migration_engine) as db:
        assert list(db.scalars(sa.select(AccessToken))) == []
        assert db.get(TargetApplication, target_id).api_key == "FAKE_MIGRATION_KEY"
        assert db.get(EvaluationRun, run_id).results[0].response == "FAKE_CANARY"
