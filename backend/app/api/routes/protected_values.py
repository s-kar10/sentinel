"""Write-safe protected-value management endpoints."""

from fastapi import APIRouter, Response, status

from app.api.dependencies import TargetServiceDependency
from app.schemas.target import ProtectedValueCreate, ProtectedValueRead

router = APIRouter(tags=["protected-values"])


@router.get(
    "/targets/{target_id}/protected-values",
    response_model=list[ProtectedValueRead],
)
def list_protected_values(
    target_id: int,
    service: TargetServiceDependency,
) -> list[ProtectedValueRead]:
    return service.list_protected_values(target_id)  # type: ignore[return-value]


@router.post(
    "/targets/{target_id}/protected-values",
    response_model=ProtectedValueRead,
    status_code=status.HTTP_201_CREATED,
)
def create_protected_value(
    target_id: int,
    payload: ProtectedValueCreate,
    service: TargetServiceDependency,
) -> ProtectedValueRead:
    return service.create_protected_value(target_id, payload)  # type: ignore[return-value]


@router.delete(
    "/protected-values/{protected_value_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_protected_value(
    protected_value_id: int,
    service: TargetServiceDependency,
) -> Response:
    service.delete_protected_value(protected_value_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
