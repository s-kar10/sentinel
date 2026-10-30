"""Explicit schema management; the API never creates or migrates tables."""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

BASELINE = "0001_v01_baseline"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class SchemaStateError(RuntimeError):
    """An actionable error that contains no database credentials or row data."""


def migration_config(connection: Connection | None = None) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def current_revisions(connection: Connection) -> tuple[str, ...]:
    return MigrationContext.configure(connection).get_current_heads()


def require_current_schema(
    engine: Engine, *, statement_timeout_ms: int | None = None
) -> None:
    """Read-only startup gate; only explicit commands can alter the schema."""

    expected = set(ScriptDirectory.from_config(migration_config()).get_heads())
    with engine.connect() as connection:
        if statement_timeout_ms is not None and connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": str(statement_timeout_ms)},
            )
        if set(current_revisions(connection)) != expected:
            raise SchemaStateError(
                "Database schema is not current. Run the migration upgrade command; "
                "for an unversioned V0.1 database, back up and run adopt-v01 first."
            )


def validate_v01_schema(connection: Connection) -> None:
    """Compare legacy structure to the frozen revision, not evolving ORM models."""

    revision = ScriptDirectory.from_config(migration_config()).get_revision(BASELINE)
    expected = revision.module.baseline_metadata()
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    if actual_tables != set(expected.tables) or inspector.get_view_names():
        raise SchemaStateError(
            "Legacy schema does not match V0.1 tables. No adoption performed."
        )

    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    if compare_metadata(context, expected):
        # Diffs can contain defaults or other sensitive SQL; do not echo them.
        raise SchemaStateError(
            "Legacy schema differs from V0.1. No adoption performed."
        )

    # Autogenerate does not reliably compare primary keys or every constraint.
    for table in expected.sorted_tables:
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            raise SchemaStateError(
                "Legacy primary key differs from V0.1. No adoption performed."
            )
        if inspector.get_check_constraints(
            table.name
        ) or inspector.get_unique_constraints(table.name):
            raise SchemaStateError(
                "Legacy constraints differ from V0.1. No adoption performed."
            )
        for index in inspector.get_indexes(table.name):
            options = dict(index.get("dialect_options", {}))
            # PostgreSQL reflects even ordinary indexes with an empty INCLUDE.
            if options.get("postgresql_include") == []:
                options.pop("postgresql_include")
            if options:
                raise SchemaStateError(
                    "Legacy index options differ from V0.1. No adoption performed."
                )
        if connection.dialect.name == "postgresql":
            identifier = next(
                column
                for column in inspector.get_columns(table.name)
                if column["name"] == "id"
            )
            default = identifier.get("default") or ""
            if not default.startswith("nextval(") or identifier.get("identity"):
                raise SchemaStateError(
                    "Legacy ID generation differs from V0.1. No adoption performed."
                )


def migrate(engine: Engine, operation: str) -> None:
    """Serialize upgrade/adoption and commit only on successful validation."""

    if operation not in {"upgrade", "adopt-v01"}:
        raise ValueError("Unsupported migration operation.")
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            # Explicit BEGIN makes DDL transactional even with sqlite3 legacy mode.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.execute(text("SET LOCAL lock_timeout = '30s'"))
            connection.execute(text("SELECT pg_advisory_xact_lock(1397050964)"))
        else:
            raise SchemaStateError(
                "Only PostgreSQL and SQLite migrations are supported."
            )

        config = migration_config(connection)
        current = current_revisions(connection)
        if operation == "adopt-v01":
            if current:
                raise SchemaStateError(
                    "Database is already versioned; use upgrade instead."
                )
            validate_v01_schema(connection)
            # Stamp this exact historical revision, never a moving 'head'.
            command.stamp(config, BASELINE)
        else:
            if not current and set(inspect(connection).get_table_names()) - {
                "alembic_version"
            }:
                raise SchemaStateError(
                    "Unversioned database contains tables. Back up, then use adopt-v01 "
                    "to validate the existing schema before upgrading."
                )
            command.upgrade(config, "head")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("upgrade", "adopt-v01", "current", "check")
    )
    args = parser.parse_args()
    # Import lazily so inspection/testing can inject an engine without connecting
    # to the configured development database.
    from app.core.config import get_settings
    from app.database.session import build_engine

    engine = None
    try:
        engine = build_engine(get_settings().resolved_database_url)
        if args.operation == "check":
            require_current_schema(engine)
            print("Database revision is current.")
        elif args.operation == "current":
            with engine.connect() as connection:
                print(", ".join(current_revisions(connection)) or "unversioned")
        else:
            migrate(engine, args.operation)
            print("Migration operation completed.")
    except SchemaStateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (SQLAlchemyError, CommandError):
        print(
            "Migration failed. Check database connectivity and schema configuration.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
