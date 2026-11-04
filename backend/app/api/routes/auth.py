"""Public mode discovery and authenticated, non-secret operator identity."""

from fastapi import APIRouter, Request

from app.api.dependencies import ApplicationSettings

router = APIRouter(tags=["access"])


@router.get("/auth/status")
def auth_status(settings: ApplicationSettings):
    return {"mode": settings.auth_mode}


@router.get("/auth/me")
def auth_me(request: Request, settings: ApplicationSettings):
    if settings.auth_mode == "local":
        return {"name": "Local developer", "role": "admin", "token_id": None}
    principal = request.state.principal
    return {
        "name": principal.name,
        "role": principal.role,
        "token_id": principal.token_id,
    }
