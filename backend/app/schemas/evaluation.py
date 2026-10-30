"""Evaluation summary and result API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.evaluation import EvaluationStatus
from app.schemas.common import ensure_utc


class CategoryBreakdown(BaseModel):
    """Aggregate metrics for one attack category."""

    total_tests: int = Field(ge=0)
    passed_tests: int = Field(ge=0)
    failed_tests: int = Field(ge=0)
    score: float = Field(ge=0, le=100)


class OutcomeMetrics(BaseModel):
    passed: int
    failed: int
    errored: int
    untested: int
    not_applicable: int
    evaluated: int
    coverage: float | None
    weighted_score: float | None


class RunMetrics(OutcomeMetrics):
    categories: dict[str, OutcomeMetrics]


class EvaluationRunRead(BaseModel):
    """Evaluation lifecycle and aggregate score returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target_application_id: int
    target_name: str
    status: EvaluationStatus
    started_at: datetime | None
    completed_at: datetime | None
    total_tests: int
    passed_tests: int
    failed_tests: int
    score: float
    category_breakdown: dict[str, CategoryBreakdown] = Field(default_factory=dict)
    created_at: datetime
    engine_version: str | None
    scoring_version: str | None
    pack_digest: str | None
    pack_snapshot: dict | None
    metrics: RunMetrics | None
    progress: dict[str, int]
    version_tags: dict[str, str | None] | None

    @field_validator("started_at", "completed_at", "created_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)


class TestResultRead(BaseModel):
    """Stored observation and verdict for a single catalog attack."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    evaluation_run_id: int
    test_name: str
    category: str
    severity: str
    prompt: str
    response: str | None
    passed: bool
    failure_reason: str | None
    duration_ms: int
    attempt_count: int | None
    outcome: Literal["passed", "failed", "errored", "untested", "not_applicable"]
    response_status: int | None
    provenance: dict | None
    assertion_results: list[dict] | None
    observation_snapshot: dict | None
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc(value)  # type: ignore[return-value]
