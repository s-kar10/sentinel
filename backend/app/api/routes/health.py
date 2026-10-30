"""Process liveness and read-only database readiness."""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.database.migrations import SchemaStateError, require_current_schema

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["sentinel-api"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return process liveness without exposing environment details."""

    return HealthResponse(status="ok", service="sentinel-api")


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    service: Literal["sentinel-api"] = "sentinel-api"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(request: Request, response: Response) -> ReadinessResponse:
    """Check connectivity and migration head without modifying the schema."""
    response.headers["Cache-Control"] = "no-store"
    try:
        require_current_schema(
            request.app.state.database_engine, statement_timeout_ms=2_000
        )
    except (SQLAlchemyError, SchemaStateError):
        # Driver errors can contain connection credentials. Never echo/log them.
        response.status_code = 503
        return ReadinessResponse(status="not_ready")
    return ReadinessResponse(status="ready")
