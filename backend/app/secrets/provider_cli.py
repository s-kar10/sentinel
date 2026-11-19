"""Provision project provider keys from private files; print metadata only."""

import argparse
import json
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.migrations import require_current_schema
from app.database.session import build_engine
from app.models.credential import CredentialAudit, ProviderCredential
from app.models.project import Project
from app.secrets.codec import read_private_file
from app.secrets.providers import put, revoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("put", "revoke", "list", "audit"):
        command = commands.add_parser(name)
        command.add_argument("--project-id", type=int, required=True)
        if name == "put":
            command.add_argument("--input-file", required=True)
        if name == "audit":
            command.add_argument("--after-id", type=int, default=0)
            command.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.project_id < 1 or (
            args.command == "audit"
            and (args.after_id < 0 or not 1 <= args.limit <= 1000)
        ):
            raise ValueError()
        secret = None
        if args.command == "put":
            secret = (
                read_private_file(args.input_file, 4098)
                .decode("ascii")
                .removesuffix("\n")
                .removesuffix("\r")
            )
        engine = build_engine(get_settings().resolved_database_url)
        require_current_schema(engine)
        with Session(engine) as db, db.begin():
            db.info["actor_kind"] = "host_cli"
            if db.get(Project, args.project_id) is None:
                raise ValueError()
            if args.command == "put":
                row = put(db, args.project_id, secret)
                output = {
                    "credential_id": row.id,
                    "version": row.version,
                    "project_id": row.project_id,
                }
            elif args.command == "revoke":
                output = {
                    "revoked": revoke(db, args.project_id),
                    "project_id": args.project_id,
                }
            elif args.command == "list":
                columns = (
                    ProviderCredential.id,
                    ProviderCredential.project_id,
                    ProviderCredential.provider,
                    ProviderCredential.version,
                    ProviderCredential.secret.is_not(None).label("active"),
                )
                output = [
                    dict(row)
                    for row in db.execute(
                        select(*columns).where(
                            ProviderCredential.project_id == args.project_id
                        )
                    ).mappings()
                ]
            else:
                rows = db.scalars(
                    select(CredentialAudit)
                    .where(
                        CredentialAudit.project_id == args.project_id,
                        CredentialAudit.id > args.after_id,
                    )
                    .order_by(CredentialAudit.id)
                    .limit(args.limit)
                )
                output = [
                    {
                        column.name: getattr(row, column.name)
                        for column in CredentialAudit.__table__.columns
                    }
                    for row in rows
                ]
        print(json.dumps(output, default=str))
        return 0
    except (OSError, ValueError, RuntimeError, SQLAlchemyError):
        print(
            "Provider credential command failed. Check project, schema and private files.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
