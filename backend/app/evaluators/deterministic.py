"""Deterministic evaluator implementations used by the MVP."""

import re
from typing import Sequence

from app.evaluators.base import EvaluationOutcome, ResponseEvaluator


def _find_case_insensitive(response: str, values: Sequence[str]) -> str | None:
    folded_response = response.casefold()
    return next(
        (value for value in values if value.casefold() in folded_response), None
    )


class ContainsForbiddenStringEvaluator(ResponseEvaluator):
    """Fail when any configured forbidden value occurs in the response."""

    name = "contains_forbidden_string"

    def evaluate(
        self,
        response: str,
        expected_values: Sequence[str],
        *,
        failure_message: str,
    ) -> EvaluationOutcome:
        evidence = _find_case_insensitive(response, expected_values)
        if evidence is not None:
            return EvaluationOutcome(False, failure_message, evidence)
        return EvaluationOutcome(True)


class DoesNotContainStringEvaluator(ContainsForbiddenStringEvaluator):
    """Explicit constraint evaluator; passes only when values remain absent."""

    name = "does_not_contain_string"


class ExactMatchEvaluator(ResponseEvaluator):
    """Pass when the stripped response exactly matches one allowed expectation."""

    name = "exact_match"

    def evaluate(
        self,
        response: str,
        expected_values: Sequence[str],
        *,
        failure_message: str,
    ) -> EvaluationOutcome:
        normalized = response.strip()
        if any(normalized == value for value in expected_values):
            return EvaluationOutcome(True)
        return EvaluationOutcome(False, failure_message, normalized[:200] or None)


class RegexMatchEvaluator(ResponseEvaluator):
    """Pass when at least one configured regular expression matches the response."""

    name = "regex_match"

    def evaluate(
        self,
        response: str,
        expected_values: Sequence[str],
        *,
        failure_message: str,
    ) -> EvaluationOutcome:
        for pattern in expected_values:
            try:
                re.compile(pattern)
            except (re.error, RecursionError, OverflowError):
                return EvaluationOutcome(
                    False, "The configured evaluation pattern is invalid."
                )
            from app.evaluators.isolation import isolated_check

            if len(pattern) > 1024 or len(response) > 100_000:
                return EvaluationOutcome(
                    False, "The evaluation input limit was exceeded."
                )
            outcome = isolated_check(
                {
                    "kind": "regex",
                    "value": response,
                    "config": {
                        "pattern": pattern,
                        "case_sensitive": False,
                        "mode": "search",
                    },
                }
            )
            if outcome.outcome == "errored":
                return EvaluationOutcome(
                    False, "The evaluation could not be completed."
                )
            if outcome.outcome == "passed":
                start, end = outcome.evidence["span"]
                return EvaluationOutcome(True, evidence=response[start:end][:200])
        return EvaluationOutcome(False, failure_message)
