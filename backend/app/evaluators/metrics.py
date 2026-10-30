"""Versioned outcome/coverage metrics; historical pass-rate storage is unchanged."""

WEIGHTS = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SCORING_VERSION = "severity-v1"


def summarize(results, weights=None):
    weights = WEIGHTS if weights is None else weights
    counts = dict.fromkeys(
        ("passed", "failed", "errored", "untested", "not_applicable"), 0
    )
    passed_weight = evaluated_weight = 0
    for result in results:
        state = result.outcome
        counts[state] += 1
        if state in {"passed", "failed"}:
            weight = weights.get(result.severity, 1)
            evaluated_weight += weight
            if state == "passed":
                passed_weight += weight
    evaluated = counts["passed"] + counts["failed"]
    applicable = len(results) - counts["not_applicable"]
    return {
        **counts,
        "evaluated": evaluated,
        "coverage": round(100 * evaluated / applicable, 2) if applicable else None,
        "weighted_score": round(100 * passed_weight / evaluated_weight, 2)
        if evaluated_weight
        else None,
    }
