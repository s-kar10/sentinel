"""Target application CRUD endpoints."""

from fastapi import APIRouter, Response, status

from app.api.dependencies import TargetServiceDependency
from app.schemas.target import TargetCreate, TargetRead, TargetUpdate

router = APIRouter(prefix="/targets", tags=["targets"])


@router.get("", response_model=list[TargetRead])
def list_targets(service: TargetServiceDependency) -> list[TargetRead]:
    return service.list_targets()  # type: ignore[return-value]


@router.post("", response_model=TargetRead, status_code=status.HTTP_201_CREATED)
def create_target(
    payload: TargetCreate, service: TargetServiceDependency
) -> TargetRead:
    return service.create_target(payload)  # type: ignore[return-value]


@router.get("/{target_id}", response_model=TargetRead)
def get_target(target_id: int, service: TargetServiceDependency) -> TargetRead:
    return service.get_target(target_id)  # type: ignore[return-value]


@router.put("/{target_id}", response_model=TargetRead)
def update_target(
    target_id: int,
    payload: TargetUpdate,
    service: TargetServiceDependency,
) -> TargetRead:
    return service.update_target(target_id, payload)  # type: ignore[return-value]


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(target_id: int, service: TargetServiceDependency) -> Response:
    service.delete_target(target_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
