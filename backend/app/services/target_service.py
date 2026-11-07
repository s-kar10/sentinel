"""Target and protected-value persistence use cases."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.scope import owned_targets
from app.models import ProtectedValue, TargetApplication
from app.schemas.target import ProtectedValueCreate, TargetCreate, TargetUpdate
from app.services.errors import InvalidTargetConfigurationError, ResourceNotFoundError
from app.utils.json_paths import JsonPathError, get_path_value


class TargetService:
    """Encapsulate target CRUD behavior and update invariants."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_targets(self) -> list[TargetApplication]:
        statement = (
            select(TargetApplication)
            .where(TargetApplication.id.in_(owned_targets(self.db)))
            .order_by(TargetApplication.created_at.desc())
        )
        return list(self.db.scalars(statement).all())

    def get_target(
        self, target_id: int, *, with_relations: bool = False
    ) -> TargetApplication:
        statement = select(TargetApplication).where(
            TargetApplication.id == target_id,
            TargetApplication.id.in_(owned_targets(self.db)),
        )
        if with_relations:
            statement = statement.options(
                selectinload(TargetApplication.protected_values),
                selectinload(TargetApplication.evaluation_runs),
            )
        target = self.db.scalar(statement)
        if target is None:
            raise ResourceNotFoundError("Target application not found.")
        return target

    def create_target(self, payload: TargetCreate) -> TargetApplication:
        values = payload.model_dump(mode="json")
        target = TargetApplication(
            project_id=self.db.info.get("project_id", 1), **values
        )
        self.db.add(target)
        self.db.commit()
        self.db.refresh(target)
        return target

    def update_target(self, target_id: int, payload: TargetUpdate) -> TargetApplication:
        target = self.get_target(target_id)
        changes = payload.model_dump(mode="json", exclude_unset=True)

        request_template = changes.get("request_template", target.request_template)
        prompt_field = changes.get("prompt_field", target.prompt_field)
        try:
            get_path_value(request_template, prompt_field)
        except JsonPathError as exc:
            raise InvalidTargetConfigurationError(
                f"prompt_field is invalid for request_template: {exc}"
            ) from exc

        for field, value in changes.items():
            setattr(target, field, value)
        self.db.commit()
        self.db.refresh(target)
        return target

    def delete_target(self, target_id: int) -> None:
        target = self.get_target(target_id)
        self.db.delete(target)
        self.db.commit()

    def list_protected_values(self, target_id: int) -> list[ProtectedValue]:
        self.get_target(target_id)
        statement = (
            select(ProtectedValue)
            .where(ProtectedValue.target_application_id == target_id)
            .order_by(ProtectedValue.created_at.desc())
        )
        return list(self.db.scalars(statement).all())

    def create_protected_value(
        self, target_id: int, payload: ProtectedValueCreate
    ) -> ProtectedValue:
        self.get_target(target_id)
        protected_value = ProtectedValue(
            target_application_id=target_id,
            **payload.model_dump(),
        )
        self.db.add(protected_value)
        self.db.commit()
        self.db.refresh(protected_value)
        return protected_value

    def delete_protected_value(self, protected_value_id: int) -> None:
        protected_value = self.db.scalar(
            select(ProtectedValue).where(
                ProtectedValue.id == protected_value_id,
                ProtectedValue.target_application_id.in_(owned_targets(self.db)),
            )
        )
        if protected_value is None:
            raise ResourceNotFoundError("Protected value not found.")
        self.get_target(protected_value.target_application_id)
        self.db.delete(protected_value)
        self.db.commit()
