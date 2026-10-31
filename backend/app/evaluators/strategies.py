"""Version 1 strategies: no orchestration or persistence knowledge."""

import json

from app.evaluators.contracts import AssertionOutcome, Outcome, verdict
from app.evaluators.isolation import isolated_check

MAX_JSON_DEPTH = 100


def check_text_depth(text):
    """Bound containers before parsing; quoted brackets are ordinary string data."""
    depth = 0
    quoted = escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise RecursionError
        elif character in "]}":
            depth -= 1


def check_value_depth(value):
    """Check already decoded document/value sources without recursive traversal."""
    stack = [(iter((value,)), 0)]
    while stack:
        children, depth = stack[-1]
        try:
            child = next(children)
        except StopIteration:
            stack.pop()
            continue
        if isinstance(child, (dict, list)):
            if depth >= MAX_JSON_DEPTH:
                raise RecursionError
            stack.append(
                (iter(child.values() if isinstance(child, dict) else child), depth + 1)
            )


def text_check(observation, config, protected_values, *, exact=False):
    if observation.content is None or observation.error:
        return AssertionOutcome(Outcome.ERRORED, "text_unavailable")
    response = (
        observation.content.strip() if config.strip_response else observation.content
    )
    values = list(config.values)
    if config.include_target_protected_values:
        values.extend(protected_values)
    if not config.case_sensitive:
        response = response.casefold()
        values = [value.casefold() for value in values]
    matched = [
        i
        for i, value in enumerate(values)
        if (response == value if exact else value in response)
    ]
    return verdict(
        bool(matched) if exact else not matched,
        "string_checked",
        matched_count=len(matched),
    )


def forbidden(observation, config, protected_values):
    return text_check(observation, config, protected_values)


def exact(observation, config, protected_values):
    return text_check(observation, config, protected_values, exact=True)


def regex(observation, config, _protected_values):
    if observation.content is None or observation.error:
        return AssertionOutcome(Outcome.ERRORED, "text_unavailable")
    if len(observation.content) > 100_000:
        return AssertionOutcome(Outcome.ERRORED, "evaluator_input_limit")
    return isolated_check(
        {"kind": "regex", "value": observation.content, "config": config.model_dump()}
    )


def latency(observation, config, _protected_values):
    if observation.status_code is None:
        return AssertionOutcome(Outcome.ERRORED, "transport_unavailable")
    return verdict(
        observation.duration_ms <= config.max_ms,
        "latency_checked",
        observed_ms=observation.duration_ms,
        max_ms=config.max_ms,
    )


def status(observation, config, _protected_values):
    if observation.status_code is None:
        return AssertionOutcome(Outcome.ERRORED, "transport_unavailable")
    return verdict(
        observation.status_code in config.allowed,
        "status_checked",
        status_code=observation.status_code,
    )


def json_value(observation, source):
    if source == "document":
        if not observation.has_document:
            raise LookupError
        return observation.document
    if source == "value":
        if not observation.has_value:
            raise LookupError
        return observation.value
    if observation.content is None:
        raise LookupError
    check_text_depth(observation.content)
    return json.loads(
        observation.content,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )


def json_check(observation, config, _protected_values):
    try:
        value = json_value(observation, config.source)
        check_value_depth(value)
    except LookupError:
        return AssertionOutcome(Outcome.ERRORED, "json_source_unavailable")
    except RecursionError:
        return AssertionOutcome(Outcome.ERRORED, "json_depth_limit")
    except ValueError:
        return verdict(False, "invalid_json")
    if hasattr(config, "schema_definition"):
        return isolated_check(
            {"kind": "schema", "value": value, "schema": config.schema_definition}
        )
    return verdict(True, "valid_json")
