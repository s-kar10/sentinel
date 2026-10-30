"""Bounded queue submission contract; bodyless requests select the baseline."""

from pydantic import BaseModel, ConfigDict, Field

from app.attacks.packs import AttackPack


class VersionTags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    application: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    prompt: str | None = Field(default=None, min_length=1, max_length=100)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    attack_pack: AttackPack | None = None
    versions: VersionTags = Field(default_factory=VersionTags)
