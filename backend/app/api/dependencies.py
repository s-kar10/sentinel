"""Route-level service construction."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.judges.runtime import settings_snapshot
from app.services.evaluation_service import EvaluationService
from app.services.target_client import TargetClient
from app.services.target_service import TargetService


def scoped_db(request: Request, db: Annotated[Session, Depends(get_db)]) -> Session:
    # Use app settings, never a client-supplied project selector. Missing token
    # identity fails closed even if a future route accidentally skips middleware.
    if request.app.state.settings.auth_mode == "local":
        project_id = 1
    else:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(401, "A valid access token is required.")
        project_id = principal.project_id
    db.info["project_id"] = project_id
    return db


DatabaseSession = Annotated[Session, Depends(scoped_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


def get_target_service(db: DatabaseSession) -> TargetService:
    return TargetService(db)


def get_evaluation_service(
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> EvaluationService:
    return EvaluationService(
        db,
        judge_runtime=settings_snapshot(settings),
        target_client_factory=lambda target: TargetClient(
            target,
            timeout_seconds=settings.target_request_timeout_seconds,
            max_response_bytes=settings.target_max_response_bytes,
        ),
    )


TargetServiceDependency = Annotated[TargetService, Depends(get_target_service)]
EvaluationServiceDependency = Annotated[
    EvaluationService, Depends(get_evaluation_service)
]
