"""Top-level API router assembly."""

from fastapi import APIRouter

from app.api.routes import auth, evaluations, health, protected_values, targets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(targets.router)
api_router.include_router(protected_values.router)
api_router.include_router(evaluations.router)
