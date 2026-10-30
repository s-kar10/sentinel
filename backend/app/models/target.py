"""Target application and protected-value models."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.evaluation import EvaluationRun


class TargetApplication(Base):
    """Configuration needed to exercise a target AI application's HTTP API."""

    __tablename__ = "target_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    http_method: Mapped[str] = mapped_column(String(10), nullable=False, default="POST")
    # TODO: Encrypt this value at rest or replace it with a secret-manager reference
    # before a production deployment. It is never exposed through response schemas.
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_template: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prompt_field: Mapped[str] = mapped_column(String(500), nullable=False)
    response_field: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    protected_values: Mapped[list["ProtectedValue"]] = relationship(
        back_populates="target_application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    evaluation_runs: Mapped[list["EvaluationRun"]] = relationship(
        back_populates="target_application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def has_api_key(self) -> bool:
        """Expose key presence without ever returning the credential."""

        return bool(self.api_key)


class ProtectedValue(Base):
    """A canary or sensitive string that must not appear in target responses."""

    __tablename__ = "protected_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_application_id: Mapped[int] = mapped_column(
        ForeignKey("target_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Protected values are treated as write-only at the API boundary.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    target_application: Mapped[TargetApplication] = relationship(
        back_populates="protected_values"
    )

    @property
    def display_value(self) -> str:
        """Return a non-reversible hint suitable for a management UI."""

        if len(self.value) <= 4:
            return "*" * len(self.value)
        return f"{self.value[:2]}{'*' * min(len(self.value) - 4, 12)}{self.value[-2:]}"
