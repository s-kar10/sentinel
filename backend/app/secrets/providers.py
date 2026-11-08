"""Project credential lifecycle and admission, with caller-owned transactions."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session, defer

from app.models.credential import CredentialAudit, ProviderCredential
from app.models.project import Project


def lock_project(db: Session, project_id: int) -> None:
    # Serialize even the first credential insert with submission/replacement/revoke.
    # Queue submission acquires its coordinator lock before this project lock.
    if (
        db.execute(
            update(Project).where(Project.id == project_id).values(name=Project.name)
        ).rowcount
        != 1
    ):
        raise ValueError("Project not found.")


def record(
    db: Session,
    runtime: dict,
    project_id: int,
    event: str,
    *,
    run_id: int | None = None,
    worker: bool = False,
) -> None:
    db.add(
        CredentialAudit(
            project_id=project_id,
            provider=runtime["provider"],
            credential_id=runtime.get("credential_id"),
            credential_version=runtime.get("credential_version"),
            source=runtime.get("credential_source", "legacy_snapshot"),
            event=event,
            run_id=run_id,
            actor_kind="worker" if worker else db.info.get("actor_kind", "internal"),
            token_id=None if worker else db.info.get("token_id"),
        )
    )


def credential_metadata(row: ProviderCredential) -> dict:
    return {
        "provider": row.provider,
        "credential_id": row.id,
        "credential_version": row.version,
        "credential_project_id": row.project_id,
        "credential_source": "project",
    }


def put(db: Session, project_id: int, secret: str) -> ProviderCredential:
    if (
        not 1 <= len(secret) <= 4096
        or not secret.isascii()
        or any(ord(c) <= 32 or ord(c) == 127 for c in secret)
    ):
        raise ValueError(
            "Provider credentials must be 1–4096 printable ASCII characters without whitespace."
        )
    lock_project(db, project_id)
    row = db.scalar(
        select(ProviderCredential)
        .where(
            ProviderCredential.project_id == project_id,
            ProviderCredential.provider == "openai",
        )
        .options(defer(ProviderCredential.secret))
        .execution_options(populate_existing=True)
    )
    event = "replaced" if row else "created"
    if row is None:
        row = ProviderCredential(project_id=project_id, provider="openai", version=1)
        db.add(row)
    else:
        row.version += 1
    row.secret = secret
    db.flush()
    record(db, credential_metadata(row), project_id, event)
    return row


def revoke(db: Session, project_id: int) -> bool:
    lock_project(db, project_id)
    row = db.scalar(
        select(ProviderCredential)
        .where(
            ProviderCredential.project_id == project_id,
            ProviderCredential.provider == "openai",
            ProviderCredential.secret.is_not(None),
        )
        .options(defer(ProviderCredential.secret))
        .execution_options(populate_existing=True)
    )
    if row is None:
        return False
    row.secret = None
    record(db, credential_metadata(row), project_id, "revoked")
    db.flush()
    return True


def resolve(db: Session, project_id: int, runtime: dict, *, auth_mode: str) -> dict:
    # The service package re-exports orchestration; keep cold CLI imports independent.
    from app.services.errors import InvalidTargetConfigurationError

    lock_project(db, project_id)
    row = db.scalar(
        select(ProviderCredential)
        .where(
            ProviderCredential.project_id == project_id,
            ProviderCredential.provider == runtime["provider"],
        )
        .execution_options(populate_existing=True)
    )
    if row is not None:
        if row.secret is None:
            raise InvalidTargetConfigurationError(
                "The project's provider credential is revoked; provision a replacement."
            )
        return {**runtime, "api_key": row.secret, **credential_metadata(row)}
    # Compatibility is deliberately limited to the unauthenticated legacy project.
    if auth_mode == "local" and project_id == 1 and runtime.get("api_key"):
        return {
            **runtime,
            "credential_source": "legacy_environment",
            "credential_project_id": project_id,
        }
    raise InvalidTargetConfigurationError(
        "Provision an active provider credential for this project using the private CLI."
    )
