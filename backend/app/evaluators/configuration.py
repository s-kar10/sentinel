"""Strict configuration models for supported evaluator version 1 contracts."""

import json
import re
from typing import Annotated, Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Value = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]
StatusCode = Annotated[int, Field(strict=True, ge=100, le=599)]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StringConfig(Config):
    values: tuple[Value, ...] = Field(default=(), max_length=20)
    case_sensitive: StrictBool = False
    strip_response: StrictBool = False
    include_target_protected_values: StrictBool = False

    @model_validator(mode="after")
    def coverage(self) -> Self:
        if not self.values and not self.include_target_protected_values:
            raise ValueError("Provide values or enable target protected values.")
        return self


class ExactConfig(StringConfig):
    case_sensitive: StrictBool = True
    strip_response: StrictBool = True

    @model_validator(mode="after")
    def explicit_values(self) -> Self:
        if self.include_target_protected_values:
            raise ValueError("Exact-match checks require explicit values.")
        return self


class RegexConfig(Config):
    pattern: Annotated[str, Field(min_length=1, max_length=1024)]
    case_sensitive: StrictBool = False
    mode: Literal["search", "fullmatch"] = "search"

    @model_validator(mode="after")
    def valid_pattern(self) -> Self:
        try:
            re.compile(self.pattern)
        except (re.error, RecursionError, OverflowError):
            raise ValueError("Invalid regular expression.") from None
        return self


class LatencyConfig(Config):
    max_ms: Annotated[int, Field(strict=True, ge=0, le=600_000)]


class StatusConfig(Config):
    allowed: tuple[StatusCode, ...] = Field(min_length=1, max_length=50)


class JsonConfig(Config):
    source: Literal["document", "value", "text_json"] = "text_json"


def validate_schema_profile(schema: Any, depth: int = 0) -> None:
    """A documented non-referencing Draft 2020-12 subset, never silently ignored."""
    if depth > 10:
        raise ValueError("Schema nesting exceeds 10 levels.")
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError("A schema must be an object or boolean.")
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "enum",
        "const",
        "title",
        "description",
    }
    if set(schema) - allowed:
        raise ValueError(
            "Unsupported schema keyword; references and patterns are disabled."
        )
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or len(properties) > 100:
        raise ValueError(
            "Schema properties must be an object with at most 100 entries."
        )
    for child in properties.values():
        validate_schema_profile(child, depth + 1)
    for key in ("items", "additionalProperties"):
        if key in schema:
            validate_schema_profile(schema[key], depth + 1)


class SchemaConfig(JsonConfig):
    schema_definition: dict[str, Any] | StrictBool

    @model_validator(mode="after")
    def valid_schema(self) -> Self:
        try:
            encoded = json.dumps(self.schema_definition, allow_nan=False)
            if len(encoded.encode("utf-8")) > 8192:
                raise ValueError("Schema exceeds 8192 bytes.")
            validate_schema_profile(self.schema_definition)
            Draft202012Validator.check_schema(self.schema_definition)
        except (SchemaError, RecursionError, UnicodeError):
            raise ValueError("Invalid JSON schema.") from None
        return self
