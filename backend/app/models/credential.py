"""Project provider credentials and append-only application audit metadata."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.secrets.types import EncryptedProviderKey


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("project_id", "provider"),
        CheckConstraint("provider = 'openai'", name="ck_provider_credential_provider"),
        CheckConstraint("version >= 1", name="ck_provider_credential_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    secret: Mapped[str | None] = mapped_column(EncryptedProviderKey(), nullable=True)


class CredentialAudit(Base):
    """No bodies, credential values, digests, URLs or free-form actor labels.

    Numeric references deliberately have no cascading FKs: deleting a target/run
    or later removing a token must not erase this history. This is not tamper-proof
    against the trusted database/host operator.
    """

    __tablename__ = "credential_audit"
    __table_args__ = (
        CheckConstraint(
            "event IN ('created','replaced','revoked','snapshotted','dispatched')",
            name="ck_credential_audit_event",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    credential_id: Mapped[int | None] = mapped_column(nullable=True)
    credential_version: Mapped[int | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    event: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    token_id: Mapped[int | None] = mapped_column(nullable=True)
    run_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
