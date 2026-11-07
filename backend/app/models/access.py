"""Local operator credentials; these do not represent tenant memberships."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.project import TokenProject


class AccessToken(Base):
    __tablename__ = "access_tokens"
    __table_args__ = (
        CheckConstraint(
            "role IN ('reader', 'runner', 'admin')", name="ck_access_token_role"
        ),
    )

    ownership: Mapped[TokenProject | None] = relationship(
        cascade="all, delete-orphan", uselist=False, lazy="joined", passive_deletes=True
    )

    def __init__(self, *, project_id=1, **kwargs):
        super().__init__(**kwargs)
        self.ownership = TokenProject(project_id=project_id)

    @property
    def project_id(self) -> int | None:
        return self.ownership.project_id if self.ownership else None

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AccessAudit(Base):
    """Credential lifecycle only; never request bodies, token values or digests."""

    __tablename__ = "access_audit"
    __table_args__ = (
        CheckConstraint("event IN ('issued', 'revoked')", name="ck_access_audit_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(nullable=False)
    event: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
