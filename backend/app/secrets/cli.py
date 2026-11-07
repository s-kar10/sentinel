"""Offline key creation, rotation and verification. Never prints secret material."""

import argparse
import base64
import json
import sys
from pathlib import Path

import sqlalchemy as sa

from app.secrets.codec import (
    Keyring,
    SecretStorageError,
    configured_keyring,
    new_keyring,
    write_keyring,
)


def rewrite(connection, ring: Keyring, *, verify_only: bool = False) -> dict[str, int]:
    """Caller stops API/workers; one transaction validates and rewrites all rows."""
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(
            sa.text("LOCK TABLE target_applications, evaluation_jobs IN EXCLUSIVE MODE")
        )
    counts = {}
    for name, pk, column, kind, purpose in (
        ("target_applications", "id", "api_key", sa.Text, "target-api-key"),
        ("evaluation_jobs", "run_id", "payload", sa.JSON, "job-payload"),
    ):
        table = sa.table(name, sa.column(pk, sa.Integer), sa.column(column, kind))
        count = 0
        for row in connection.execute(sa.select(table)).mappings():
            value = row[column]
            if value is None:
                continue
            if column == "payload":
                if not isinstance(value, dict) or set(value) != {"encrypted"}:
                    raise SecretStorageError()
                value = value["encrypted"]
            plaintext = ring.open(value, purpose)
            if not verify_only:
                encrypted = ring.seal(plaintext, purpose)
                connection.execute(
                    table.update()
                    .where(table.c[pk] == row[pk])
                    .values(
                        {
                            column: {"encrypted": encrypted}
                            if column == "payload"
                            else encrypted
                        }
                    )
                )
            count += 1
        counts[name] = count
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "add-key"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name == "add-key":
            command.add_argument("--source", required=True)
    commands.add_parser("reencrypt")
    commands.add_parser("verify")
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.command in {"init", "add-key"}:
            value = new_keyring()
            if args.command == "add-key":
                old = Keyring(args.source)
                if len(old.keys) >= 32:
                    raise SecretStorageError()
                value["keys"].update(
                    {
                        key: base64.b64encode(data).decode()
                        for key, data in old.keys.items()
                    }
                )
            write_keyring(args.output, value)
            print("Keyring written to the requested private file.")
        else:
            from app.core.config import get_settings
            from app.database.migrations import require_current_schema
            from app.database.session import build_engine

            ring = configured_keyring()
            engine = build_engine(get_settings().resolved_database_url)
            require_current_schema(engine)
            with engine.begin() as connection:
                counts = rewrite(connection, ring, verify_only=args.command == "verify")
            print(json.dumps({"operation": args.command, "records": counts}))
        return 0
    except (OSError, ValueError, RuntimeError, sa.exc.SQLAlchemyError):
        print(
            "Secret operation failed. Check schema, private keyring and stopped services.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
