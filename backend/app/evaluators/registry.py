"""Evaluator discovery without conditionals in the evaluation service."""

from collections.abc import Iterable

from app.evaluators.base import ResponseEvaluator
from app.evaluators.deterministic import (
    ContainsForbiddenStringEvaluator,
    DoesNotContainStringEvaluator,
    ExactMatchEvaluator,
    RegexMatchEvaluator,
)


class EvaluatorRegistry:
    """Immutable-by-convention registry of named evaluator strategies."""

    def __init__(self, evaluators: Iterable[ResponseEvaluator]) -> None:
        self._evaluators = {evaluator.name: evaluator for evaluator in evaluators}

    def get(self, name: str) -> ResponseEvaluator:
        try:
            return self._evaluators[name]
        except KeyError as exc:
            raise ValueError(f"Unknown evaluator '{name}'.") from exc


default_evaluator_registry = EvaluatorRegistry(
    (
        ContainsForbiddenStringEvaluator(),
        DoesNotContainStringEvaluator(),
        ExactMatchEvaluator(),
        RegexMatchEvaluator(),
    )
)
