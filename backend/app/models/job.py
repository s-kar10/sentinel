"""Private durable dispatch state. Never serialize these models to API responses."""

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class QueueControl(Base):
    __tablename__ = "queue_control"
    id: Mapped[int] = mapped_column(primary_key=True)
    next_dispatch: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"
    run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), primary_key=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("target_applications.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    deadline: Mapped[float] = mapped_column(Float, nullable=False)
    lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    token: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
