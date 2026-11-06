"""Stored baseline management and bounded historical queries."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.auth.scope import owned_targets
from app.models import EvaluationRun
from app.models.baseline import Baseline
from app.services.comparison import (
    ANALYSIS_VERSION,
    compare_runs,
    point,
    repeated_regressions,
)
from app.services.errors import (
    ConflictError,
    InvalidTargetConfigurationError,
    ResourceNotFoundError,
)
from app.services.evaluation_service import EvaluationService
from app.services.provenance import redact


class HistoryService:
    def __init__(self, db):
        self.db = db
        self.evaluations = EvaluationService(db, target_client_factory=lambda _: None)

    def create_baseline(self, target_id, run_id, name):
        self.evaluations._get_target(target_id)
        run = self.evaluations.get_run(run_id)
        if (
            run.target_application_id != target_id
            or run.status != "completed"
            or not run.comparison_key
            or not run.metrics
            or run.metrics["evaluated"] == 0
            or run.metrics["coverage"] != 100
        ):
            raise InvalidTargetConfigurationError(
                "Choose a completed compatible run with full coverage and at least one behavioral result."
            )
        target = self.evaluations._get_target(target_id)
        name = redact(
            name, [v.value for v in target.protected_values] + [target.api_key or ""]
        )
        baseline = Baseline(target_id=target_id, run_id=run_id, name=name)
        self.db.add(baseline)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(
                "A baseline with this name already exists; choose a new name."
            ) from None
        return baseline

    def list_baselines(self, target_id):
        self.evaluations._get_target(target_id)
        return list(
            self.db.scalars(
                select(Baseline)
                .where(Baseline.target_id == target_id)
                .order_by(Baseline.id.desc())
            )
        )

    def baseline(self, baseline_id):
        baseline = self.db.scalar(
            select(Baseline).where(
                Baseline.id == baseline_id,
                Baseline.target_id.in_(owned_targets(self.db)),
            )
        )
        if baseline is None:
            raise ResourceNotFoundError("Baseline not found.")
        return self.evaluations.get_run(baseline.run_id)

    def comparison(self, run_id, baseline_id):
        return compare_runs(
            self.baseline(baseline_id), self.evaluations.get_run(run_id)
        )

    def analytics(self, target_id, baseline_id, limit=50, through_run_id=None):
        self.evaluations._get_target(target_id)
        baseline = self.baseline(baseline_id)
        if baseline.target_application_id != target_id:
            raise InvalidTargetConfigurationError(
                "Baseline belongs to a different target."
            )
        through_run_id = (
            through_run_id
            or self.db.scalar(
                select(func.max(EvaluationRun.id)).where(
                    EvaluationRun.target_application_id == target_id
                )
            )
            or 0
        )
        statement = (
            select(EvaluationRun)
            .where(
                EvaluationRun.target_application_id == target_id,
                EvaluationRun.id <= through_run_id,
            )
            .options(selectinload(EvaluationRun.results))
            .order_by(EvaluationRun.id.desc())
            .limit(limit + 1)
        )
        selected = list(self.db.scalars(statement))
        truncated = len(selected) > limit
        runs = list(reversed(selected[:limit]))
        return {
            "analysis_version": ANALYSIS_VERSION,
            "baseline_run_id": baseline.id,
            "through_run_id": through_run_id,
            "limit": limit,
            "truncated": truncated,
            "points": [point(run, baseline) for run in runs],
            "repetition": repeated_regressions(baseline, runs),
        }
