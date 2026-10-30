"""Typed, immutable security attack definitions."""

from dataclasses import dataclass
from enum import StrEnum


class AttackCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    SYSTEM_PROMPT_LEAKAGE = "system_prompt_leakage"
    SENSITIVE_INFORMATION_LEAKAGE = "sensitive_information_leakage"
    RELIABILITY = "reliability"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class AttackDefinition:
    """One deterministic attack and the rule used to grade its response."""

    id: str
    name: str
    category: AttackCategory
    description: str
    prompt: str
    severity: Severity
    evaluator: str
    forbidden_values: tuple[str, ...] = ()
    include_target_protected_values: bool = False
    failure_message: str = "The response violated the expected safety behavior."
    version: int = 1
    # Canonical JSON keeps nested evaluator configuration immutable internally.
    assertions: tuple[str, ...] = ()
