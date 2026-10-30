"""Extensible strategy/configuration registry for versioned assertions."""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluators import strategies
from app.evaluators.configuration import (
    ExactConfig,
    JsonConfig,
    LatencyConfig,
    RegexConfig,
    SchemaConfig,
    StatusCode,
    StatusConfig,
    StringConfig,
)
from app.evaluators.contracts import AssertionOutcome, Outcome
from app.judges.contracts import JudgeConfig
from app.judges.runtime import evaluate as evaluate_judge

if TYPE_CHECKING:
    from app.services.target_client import TargetResponse


@dataclass(frozen=True)
class Strategy:
    name: str
    version: int
    config_model: type[BaseModel]
    evaluate: Callable[["TargetResponse", Any, tuple[str, ...]], AssertionOutcome]


class AssertionRegistry:
    def __init__(self, strategies: Iterable[Strategy] = ()) -> None:
        self._strategies: dict[tuple[str, int], Strategy] = {}
        for strategy in strategies:
            self.register(strategy)

    def register(self, strategy: Strategy) -> None:
        key = (strategy.name, strategy.version)
        if key in self._strategies:
            raise ValueError("Duplicate evaluator name/version.")
        self._strategies[key] = strategy

    def prepare(
        self, name: str, version: int, config: dict
    ) -> tuple[Strategy, BaseModel]:
        strategy = self._strategies.get((name, version))
        if strategy is None:
            raise ValueError("Unknown evaluator or unsupported evaluator version.")
        return strategy, strategy.config_model.model_validate(config)


registry = AssertionRegistry(
    [
        Strategy("contains_forbidden_string", 1, StringConfig, strategies.forbidden),
        Strategy("does_not_contain_string", 1, StringConfig, strategies.forbidden),
        Strategy("exact_match", 1, ExactConfig, strategies.exact),
        Strategy("regex_match", 1, RegexConfig, strategies.regex),
        Strategy("json_valid", 1, JsonConfig, strategies.json_check),
        Strategy("json_schema", 1, SchemaConfig, strategies.json_check),
        Strategy("latency", 1, LatencyConfig, strategies.latency),
        Strategy("status_code", 1, StatusConfig, strategies.status),
        Strategy("llm_judge", 1, JudgeConfig, evaluate_judge),
    ]
)


class AssertionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evaluator: str = Field(min_length=1, max_length=64)
    version: int = Field(strict=True, ge=1)
    config: dict[str, Any] = Field(default_factory=dict)
    when_status_codes: tuple[StatusCode, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        registry.prepare(self.evaluator, self.version, self.config)
        return self


def evaluate_assertion(
    spec: dict,
    observation: "TargetResponse",
    protected_values: tuple[str, ...],
    evaluator_registry: AssertionRegistry = registry,
) -> AssertionOutcome:
    strategy, config = evaluator_registry.prepare(
        spec["evaluator"], spec["version"], spec["config"]
    )
    condition = spec.get("when_status_codes", ())
    if condition and observation.status_code is None:
        return AssertionOutcome(Outcome.ERRORED, "transport_unavailable")
    if condition and observation.status_code not in condition:
        return AssertionOutcome(Outcome.NOT_APPLICABLE, "status_condition_not_met")
    try:
        outcome = strategy.evaluate(observation, config, protected_values)
        if (
            not isinstance(outcome, AssertionOutcome)
            or not isinstance(outcome.outcome, Outcome)
            or not isinstance(outcome.evidence, dict)
            or not isinstance(outcome.code, str)
            or len(outcome.code) > 100
        ):
            return AssertionOutcome(Outcome.ERRORED, "invalid_evaluator_outcome")
        if len(json.dumps(outcome.evidence, allow_nan=False).encode()) > 4096:
            return AssertionOutcome(Outcome.ERRORED, "evidence_limit")
        return outcome
    except Exception:
        return AssertionOutcome(Outcome.ERRORED, "evaluator_failed")
