"""Evaluation run and individual test-result models."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.evaluators.metrics import summarize

if TYPE_CHECKING:
    from app.models.target import TargetApplication


class EvaluationStatus(StrEnum):
    """Lifecycle states for a synchronous (and future queued) evaluation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationRun(Base):
    """Aggregate state and score for one pass through the attack catalog."""

    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_application_id: Mapped[int] = mapped_column(
        ForeignKey("target_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[EvaluationStatus] = mapped_column(
        SqlEnum(EvaluationStatus, native_enum=False, length=20),
        nullable=False,
        default=EvaluationStatus.PENDING,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    engine_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    scoring_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pack_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pack_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    comparison_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    target_application: Mapped["TargetApplication"] = relationship(
        back_populates="evaluation_runs"
    )
    results: Mapped[list["TestResult"]] = relationship(
        back_populates="evaluation_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestResult.id",
    )

    @property
    def progress(self) -> dict[str, int]:
        return {
            "planned": len(self.results),
            "completed": sum(r.outcome != "untested" for r in self.results),
            "errored": sum(r.outcome == "errored" for r in self.results),
        }

    @property
    def target_name(self) -> str:
        return self.target_application.name

    @property
    def metrics(self) -> dict | None:
        if self.engine_version is None:
            return None
        weights = (self.pack_snapshot or {}).get("severity_weights")
        return {
            **summarize(self.results, weights),
            "categories": {
                category: summarize(
                    [result for result in self.results if result.category == category],
                    weights,
                )
                for category in sorted({result.category for result in self.results})
            },
        }

    @property
    def category_breakdown(self) -> dict[str, dict[str, int | float]]:
        """Compute category metrics from results without duplicating stored state."""

        breakdown: dict[str, dict[str, int | float]] = {}
        for result in self.results:
            category = breakdown.setdefault(
                result.category,
                {"total_tests": 0, "passed_tests": 0, "failed_tests": 0, "score": 0.0},
            )
            category["total_tests"] += 1
            category["passed_tests" if result.passed else "failed_tests"] += 1

        for category in breakdown.values():
            total = int(category["total_tests"])
            passed = int(category["passed_tests"])
            category["score"] = round((passed / total) * 100, 2) if total else 0.0
        return breakdown


class TestResult(Base):
    """The observed response and deterministic verdict for one attack."""

    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_code: Mapped[str | None] = mapped_column(
        "outcome", String(30), nullable=True
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assertion_results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    observation_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    evaluation_run: Mapped[EvaluationRun] = relationship(back_populates="results")

    @property
    def outcome(self) -> str:
        return self.outcome_code or (
            "passed"
            if self.passed
            else "errored"
            if self.response is None
            else "failed"
        )
