"""Versioned observation/assertion contracts independent of orchestration."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    UNTESTED = "untested"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class AssertionOutcome:
    outcome: Outcome
    code: str
    evidence: dict[str, Any] = field(default_factory=dict)


def verdict(passed: bool, code: str, **evidence) -> AssertionOutcome:
    return AssertionOutcome(
        Outcome.PASSED if passed else Outcome.FAILED, code, evidence
    )


def aggregate(outcomes: list[str]) -> str:
    # An incomplete assertion set must never appear as a behavioral pass.
    for state in ("errored", "untested", "failed"):
        if state in outcomes:
            return state
    return "passed" if "passed" in outcomes else "not_applicable"
