"""FastAPI application factory and production entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from app.api.router import api_router
from app.auth.middleware import AccessMiddleware
from app.auth.policy import PUBLIC_GET
from app.core.config import Settings, get_settings
from app.database.migrations import require_current_schema
from app.database.session import engine
from app.secrets.codec import SecretStorageError, configured_keyring
from app.services.errors import (
    ConflictError,
    EvaluationExecutionError,
    InvalidTargetConfigurationError,
    ResourceNotFoundError,
)

_SENSITIVE_VALIDATION_FIELDS = frozenset(
    {"api_key", "value", "endpoint_url", "attack_pack", "versions"}
)


def _redact_sensitive_input(value: Any) -> Any:
    """Remove write-only fields even from validation-error echoes."""

    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key in _SENSITIVE_VALIDATION_FIELDS
            else _redact_sensitive_input(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_input(item) for item in value]
    return value


def create_app(
    application_settings: Settings | None = None,
    *,
    database_engine: Engine | None = None,
) -> FastAPI:
    """Create an app, optionally injecting isolated settings/engine for tests."""

    resolved_settings = application_settings or get_settings()
    resolved_engine = database_engine or engine

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        require_current_schema(resolved_engine)
        configured_keyring()
        yield

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.auth_mode == "local" else None,
        redoc_url="/redoc" if resolved_settings.auth_mode == "local" else None,
    )
    application.state.database_engine = resolved_engine
    application.state.settings = resolved_settings
    application.add_middleware(
        AccessMiddleware,
        engine=resolved_engine,
        mode=resolved_settings.auth_mode,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)

    if resolved_settings.auth_mode == "token":

        def protected_openapi():
            if application.openapi_schema is None:
                schema = get_openapi(
                    title=application.title,
                    version=application.version,
                    routes=application.routes,
                )
                schema.setdefault("components", {}).setdefault("securitySchemes", {})[
                    "OperatorToken"
                ] = {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque operator token",
                }
                for path, operations in schema["paths"].items():
                    for method, operation in operations.items():
                        if method == "get" and path in PUBLIC_GET:
                            continue
                        operation["security"] = [{"OperatorToken": []}]
                application.openapi_schema = schema
            return application.openapi_schema

        application.openapi = protected_openapi

    if application_settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings

    @application.exception_handler(SecretStorageError)
    async def unavailable_secrets(_: Request, exc: SecretStorageError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @application.exception_handler(ConflictError)
    async def conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(ResourceNotFoundError)
    async def resource_not_found(
        _: Request, exc: ResourceNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(InvalidTargetConfigurationError)
    async def invalid_target(
        _: Request, exc: InvalidTargetConfigurationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.exception_handler(EvaluationExecutionError)
    async def failed_evaluation(
        _: Request, exc: EvaluationExecutionError
    ) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @application.exception_handler(RequestValidationError)
    async def safe_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for original_error in exc.errors():
            error = dict(original_error)
            if "input" in error:
                location = error.get("loc", ())
                if any(part in _SENSITIVE_VALIDATION_FIELDS for part in location):
                    error["input"] = "[REDACTED]"
                else:
                    error["input"] = _redact_sensitive_input(error["input"])
            errors.append(error)
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(errors)},
        )

    return application


app = create_app()
