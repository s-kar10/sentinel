"""Validated, data-only packs at the external evaluation boundary."""

from dataclasses import asdict
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.attacks.definitions import AttackCategory, AttackDefinition, Severity
from app.evaluators.engine import AssertionSpec

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
Version = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Text = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"\S")]
ExpectedValue = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]


class PackAttack(BaseModel):
    """External attack format; no code, imports, templates, or regex execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    version: Version
    name: Name
    category: AttackCategory
    description: Text
    prompt: Text
    severity: Severity
    evaluator: (
        Literal["contains_forbidden_string", "does_not_contain_string", "exact_match"]
        | None
    ) = None
    assertions: tuple[AssertionSpec, ...] = Field(default=(), max_length=10)
    expected_values: tuple[ExpectedValue, ...] = Field(default=(), max_length=20)
    include_target_protected_values: StrictBool = False
    failure_message: Text = "The response violated the expected safety behavior."

    @model_validator(mode="after")
    def require_expectations(self) -> Self:
        if self.assertions:
            if sum(a.evaluator == "llm_judge" for a in self.assertions) > 1:
                raise ValueError("At most one semantic judge assertion per attack.")
            if (
                self.evaluator
                or self.expected_values
                or self.include_target_protected_values
            ):
                raise ValueError("Use assertions or legacy evaluator fields, not both.")
            return self
        if not self.evaluator:
            raise ValueError("Provide an evaluator or assertions.")
        if not self.expected_values and not self.include_target_protected_values:
            raise ValueError(
                "Provide expected_values or enable target protected values."
            )
        if self.evaluator == "exact_match" and self.include_target_protected_values:
            raise ValueError("Exact-match checks require explicit expected_values.")
        return self

    def to_definition(self) -> AttackDefinition:
        fields = self.model_dump()
        fields["forbidden_values"] = fields.pop("expected_values")
        fields["assertions"] = tuple(item.model_dump_json() for item in self.assertions)
        fields["evaluator"] = self.evaluator or "assertions"
        return AttackDefinition(**fields)

    @classmethod
    def from_definition(cls, attack: AttackDefinition) -> Self:
        fields = asdict(attack)
        fields["expected_values"] = fields.pop("forbidden_values")
        fields["assertions"] = tuple(
            AssertionSpec.model_validate_json(item) for item in attack.assertions
        )
        if fields["assertions"]:
            fields["evaluator"] = None
        return cls.model_validate(fields)


class AttackPack(BaseModel):
    """An ordered, immutable collection with explicit format/content revisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # A strict integer avoids accepting true or 1.0 as the format revision.
    schema_version: Annotated[int, Field(strict=True, ge=1, le=2)]
    id: Identifier
    version: Version
    name: Name
    attacks: tuple[PackAttack, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        if any(
            bool(attack.assertions) != (self.schema_version == 2)
            for attack in self.attacks
        ):
            raise ValueError(
                "Format 1 requires legacy evaluators; format 2 requires assertions."
            )
        if len({attack.id for attack in self.attacks}) != len(self.attacks):
            raise ValueError("Attack IDs must be unique within a pack.")
        # Bound the accepted normalized pack as well as individual fields. This
        # runs after JSON parsing; it is not an HTTP request-body size limit.
        if len(self.model_dump_json().encode("utf-8")) > 65_536:
            raise ValueError("The normalized attack pack exceeds 65536 bytes.")
        return self

    def definitions(self) -> tuple[AttackDefinition, ...]:
        return tuple(attack.to_definition() for attack in self.attacks)


class EvaluationStartRequest(BaseModel):
    """A supplied body must explicitly select a pack; no body uses the default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attack_pack: AttackPack
