"""Canonical evaluator snapshots and deliberately narrow secret redaction."""

import json
import re
from dataclasses import asdict

from app.evaluators.engine import registry


def assertion_definitions(attack, evaluator_registry=registry):
    if attack.assertions:
        specs = [json.loads(item) for item in attack.assertions]
    else:
        specs = [
            {
                "evaluator": attack.evaluator,
                "version": 1,
                "config": {
                    "values": attack.forbidden_values,
                    "include_target_protected_values": attack.include_target_protected_values,
                },
                "when_status_codes": [],
            }
        ]
    for spec in specs:
        _, config = evaluator_registry.prepare(
            spec["evaluator"], spec["version"], spec["config"]
        )
        spec["config"] = config.model_dump(mode="json")
    return specs


def redact(value, secrets):
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret:
                value = re.sub(
                    re.escape(secret),
                    lambda _: "[REDACTED]",
                    value,
                    flags=re.IGNORECASE,
                )
        return value
    if isinstance(value, dict):
        return {
            redact(key, secrets): redact(item, secrets) for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [redact(item, secrets) for item in value]
    return value


def attack_snapshot(attack, specs):
    value = asdict(attack)
    value.pop("forbidden_values")
    value.pop("include_target_protected_values")
    value.pop("evaluator")
    value["assertions"] = specs
    return value


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
