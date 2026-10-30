"""Baseline references are append-only; changing a reference requires a new name."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ensure_utc


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)


class BaselineRead(BaselineRequest):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_id: int
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize(cls, value):
        return ensure_utc(value)
