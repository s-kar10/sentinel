"""Manage local operator tokens without putting credentials in stdout or argv."""

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.tokens import Role, issue, revoke
from app.core.config import get_settings
from app.database.migrations import SchemaStateError, require_current_schema
from app.database.session import build_engine
from app.models.access import AccessAudit, AccessToken


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("issue")
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=[r.value for r in Role], required=True)
    create.add_argument("--days", type=int, default=7)
    create.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New private file; existing paths are never overwritten",
    )
    cancel = commands.add_parser("revoke")
    cancel.add_argument("token_id", type=int)
    commands.add_parser("list")
    commands.add_parser("audit")
    args = parser.parse_args(argv)
    engine = None
    created_file = None
    try:
        engine = build_engine(get_settings().resolved_database_url)
        require_current_schema(engine)
        with Session(engine) as db, db.begin():
            if args.command == "issue":
                # O_EXCL refuses existing files and symlinks. Mode 0600 is set at
                # creation, so there is no window with broader permissions.
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created_file = args.output
                with os.fdopen(fd, "w") as output:
                    row, value = issue(db, args.name, Role(args.role), args.days)
                    output.write(value + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                token_id = row.id
            elif args.command == "revoke":
                if (
                    not revoke(db, args.token_id)
                    and db.get(AccessToken, args.token_id) is None
                ):
                    raise ValueError("Access token not found.")
            elif args.command == "list":
                rows = db.scalars(select(AccessToken).order_by(AccessToken.id)).all()
                print(
                    json.dumps(
                        [
                            {
                                "id": r.id,
                                "name": r.name,
                                "role": r.role,
                                "expires_at": r.expires_at.isoformat(),
                                "revoked": r.revoked_at is not None,
                            }
                            for r in rows
                        ]
                    )
                )
            else:
                rows = db.scalars(select(AccessAudit).order_by(AccessAudit.id)).all()
                print(
                    json.dumps(
                        [
                            {
                                "id": r.id,
                                "token_id": r.token_id,
                                "event": r.event,
                                "created_at": r.created_at.isoformat(),
                            }
                            for r in rows
                        ]
                    )
                )
        created_file = None
        if args.command == "issue":
            print(
                f"Created access token {token_id}; credential written to the requested private file."
            )
        elif args.command == "revoke":
            print("Access token revoked.")
        return 0
    except (OSError, SQLAlchemyError, SchemaStateError, ValueError):
        if created_file is not None:
            created_file.unlink(missing_ok=True)
        print(
            "Access command failed. Check the current schema, arguments and private output path.",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
