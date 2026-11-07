"""Opaque high-entropy tokens, stored as hashes and checked on every request."""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.access import AccessAudit, AccessToken
from app.models.project import Project

TOKEN_PATTERN = re.compile(r"snt_[A-Za-z0-9_-]{43}")


class Role(StrEnum):
    READER = "reader"
    RUNNER = "runner"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    token_id: int
    name: str
    role: Role
    project_id: int
    project_name: str
    organization_id: int
    organization_name: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def issue(
    db: Session, name: str, role: Role, days: int = 7, *, project_id: int = 1
) -> tuple[AccessToken, str]:
    """Stage issuance and audit atomically; the caller owns the transaction."""
    if not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError("Token name must be 1–100 printable characters.")
    if not 1 <= days <= 90 or not isinstance(role, Role):
        raise ValueError("Use a supported role and a lifetime of 1–90 days.")
    if db.get(Project, project_id) is None:
        raise ValueError("Project not found.")
    value = "snt_" + secrets.token_urlsafe(32)
    row = AccessToken(
        project_id=project_id,
        name=name.strip(),
        role=role.value,
        digest=digest(value),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(row)
    db.flush()
    db.add(AccessAudit(token_id=row.id, event="issued"))
    return row, value


def authenticate(db: Session, value: str) -> Principal | None:
    if not TOKEN_PATTERN.fullmatch(value):
        return None
    row = db.scalar(
        select(AccessToken).where(
            AccessToken.digest == digest(value),
            AccessToken.revoked_at.is_(None),
            AccessToken.expires_at > datetime.now(timezone.utc),
        )
    )
    if row is None or row.ownership is None:
        return None
    project = row.ownership.project
    return Principal(
        row.id,
        row.name,
        Role(row.role),
        project.id,
        project.name,
        project.organization_id,
        project.organization.name,
    )


def revoke(db: Session, token_id: int) -> bool:
    result = db.execute(
        update(AccessToken)
        .where(
            AccessToken.id == token_id,
            AccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    if result.rowcount:
        db.add(AccessAudit(token_id=token_id, event="revoked"))
        return True
    return False
