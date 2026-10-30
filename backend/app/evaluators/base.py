"""Contracts shared by deterministic and future judge-based evaluators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    passed: bool
    reason: str | None = None
    evidence: str | None = None


class ResponseEvaluator(ABC):
    """Stable interface for grading an untrusted target response."""

    name: str

    @abstractmethod
    def evaluate(
        self,
        response: str,
        expected_values: Sequence[str],
        *,
        failure_message: str,
    ) -> EvaluationOutcome:
        """Evaluate a response without executing or interpreting its contents."""
