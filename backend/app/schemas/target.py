"""Target and protected-value API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.schemas.common import ensure_utc
from app.utils.json_paths import JsonPathError, get_path_value, validate_path_syntax


def _strip_nonempty(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Value must not be blank.")
    return stripped


class TargetCreate(BaseModel):
    """Configuration accepted when registering a target."""

    name: str = Field(min_length=1, max_length=200)
    endpoint_url: HttpUrl = Field(max_length=2048)
    http_method: Literal["POST"] = "POST"
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    request_template: dict[str, Any]
    prompt_field: str = Field(min_length=1, max_length=500)
    response_field: str = Field(min_length=1, max_length=500)

    @field_validator("name", "prompt_field", "response_field")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return _strip_nonempty(value)

    @field_validator("response_field")
    @classmethod
    def validate_response_path(cls, value: str) -> str:
        try:
            return validate_path_syntax(value)
        except JsonPathError as exc:
            raise ValueError(f"response_field has invalid syntax: {exc}") from exc

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value if value.strip() else None

    @field_validator("endpoint_url")
    @classmethod
    def reject_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("endpoint_url must not contain embedded credentials.")
        return value

    @model_validator(mode="after")
    def prompt_path_exists(self) -> "TargetCreate":
        try:
            get_path_value(self.request_template, self.prompt_field)
        except JsonPathError as exc:
            raise ValueError(
                f"prompt_field is invalid for request_template: {exc}"
            ) from exc
        return self


class TargetUpdate(BaseModel):
    """Fields that may be updated; omitted API keys remain unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint_url: HttpUrl | None = Field(default=None, max_length=2048)
    http_method: Literal["POST"] | None = None
    # Explicit null clears the key, while omission preserves it.
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    request_template: dict[str, Any] | None = None
    prompt_field: str | None = Field(default=None, min_length=1, max_length=500)
    response_field: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("name", "prompt_field", "response_field")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _strip_nonempty(value) if value is not None else None

    @field_validator("response_field")
    @classmethod
    def validate_optional_response_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_path_syntax(value)
        except JsonPathError as exc:
            raise ValueError(f"response_field has invalid syntax: {exc}") from exc

    @field_validator("api_key")
    @classmethod
    def normalize_optional_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value if value.strip() else None

    @field_validator("endpoint_url")
    @classmethod
    def reject_optional_url_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.username or value.password):
            raise ValueError("endpoint_url must not contain embedded credentials.")
        return value

    @model_validator(mode="after")
    def validate_update_fields(self) -> "TargetUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        non_nullable = self.model_fields_set - {"api_key"}
        if any(getattr(self, field) is None for field in non_nullable):
            raise ValueError("Target configuration fields cannot be null.")
        return self


class TargetRead(BaseModel):
    """Safe target representation; credentials are intentionally absent."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    endpoint_url: str
    http_method: str
    request_template: dict[str, Any]
    prompt_field: str
    response_field: str
    has_api_key: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return ensure_utc(value)  # type: ignore[return-value]


class ProtectedValueCreate(BaseModel):
    """A write-only protected string associated with a target."""

    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=4096, repr=False)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _strip_nonempty(value)

    @field_validator("value")
    @classmethod
    def reject_blank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Protected value must not be blank.")
        return value


class ProtectedValueRead(BaseModel):
    """Protected-value metadata with a masked, non-reversible display hint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target_application_id: int
    name: str
    display_value: str
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc(value)  # type: ignore[return-value]
