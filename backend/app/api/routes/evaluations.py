"""Evaluation execution and report endpoints."""

from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.api.dependencies import (
    ApplicationSettings,
    DatabaseSession,
    EvaluationServiceDependency,
)
from app.attacks.catalog import BUILTIN_ATTACK_PACK
from app.attacks.packs import AttackPack, EvaluationStartRequest
from app.attacks.security import SECURITY_PACKS
from app.schemas.evaluation import EvaluationRunRead, TestResultRead
from app.schemas.history import BaselineRead, BaselineRequest
from app.schemas.job import JobRequest
from app.services.history_service import HistoryService
from app.services.job_service import JobService

router = APIRouter(tags=["evaluations"])


@router.get("/attack-packs", response_model=list[AttackPack])
def list_attack_packs() -> list[AttackPack]:
    """Export built-in definitions; submitted custom packs are not stored here."""

    return [BUILTIN_ATTACK_PACK, *SECURITY_PACKS]


@router.post(
    "/targets/{target_id}/evaluations",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
def start_evaluation(
    target_id: int,
    service: EvaluationServiceDependency,
    request: EvaluationStartRequest | None = None,
) -> EvaluationRunRead:
    """Run an explicit custom pack, or the default catalog when no body is sent."""

    return service.start(
        target_id, attack_pack=request.attack_pack if request else None
    )  # type: ignore[return-value]


@router.get("/evaluations", response_model=list[EvaluationRunRead])
def list_evaluations(
    service: EvaluationServiceDependency,
    target_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[EvaluationRunRead]:
    return service.list_runs(target_id=target_id)  # type: ignore[return-value]


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationRunRead)
def get_evaluation(
    evaluation_id: int,
    service: EvaluationServiceDependency,
) -> EvaluationRunRead:
    return service.get_run(evaluation_id)  # type: ignore[return-value]


@router.get(
    "/evaluations/{evaluation_id}/results",
    response_model=list[TestResultRead],
)
def get_evaluation_results(
    evaluation_id: int,
    service: EvaluationServiceDependency,
) -> list[TestResultRead]:
    """Return a plain array so clients can consume the report predictably."""

    return service.get_results(evaluation_id)  # type: ignore[return-value]


@router.post(
    "/targets/{target_id}/evaluation-jobs",
    response_model=EvaluationRunRead,
    status_code=202,
)
def submit_evaluation(
    target_id: int,
    db: DatabaseSession,
    settings: ApplicationSettings,
    request: JobRequest | None = None,
    idempotency_key: Annotated[
        str | None, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    ] = None,
):
    return JobService(db, settings).submit(
        target_id,
        attack_pack=request.attack_pack if request else None,
        idempotency_key=idempotency_key,
        versions=request.versions.model_dump() if request else None,
    )


@router.post("/evaluations/{evaluation_id}/cancel", response_model=EvaluationRunRead)
def cancel_evaluation(evaluation_id: int, db: DatabaseSession):
    return JobService(db).cancel(evaluation_id)


@router.post(
    "/targets/{target_id}/baselines", response_model=BaselineRead, status_code=201
)
def create_baseline(target_id: int, request: BaselineRequest, db: DatabaseSession):
    return HistoryService(db).create_baseline(target_id, request.run_id, request.name)


@router.get("/targets/{target_id}/baselines", response_model=list[BaselineRead])
def list_baselines(target_id: int, db: DatabaseSession):
    return HistoryService(db).list_baselines(target_id)


@router.get("/evaluations/{evaluation_id}/comparison")
def compare_evaluation(
    evaluation_id: int, baseline_id: Annotated[int, Query(ge=1)], db: DatabaseSession
):
    return HistoryService(db).comparison(evaluation_id, baseline_id)


@router.get("/targets/{target_id}/analytics")
def historical_analytics(
    target_id: int,
    baseline_id: Annotated[int, Query(ge=1)],
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    through_run_id: Annotated[int | None, Query(ge=1)] = None,
):
    return HistoryService(db).analytics(target_id, baseline_id, limit, through_run_id)
