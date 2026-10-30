"""One isolated case. Input/output are JSON pipes, never command-line secrets."""

import json
import os
import signal
import sys

from app.attacks.definitions import AttackCategory, AttackDefinition, Severity
from app.models import ProtectedValue, TargetApplication, TestResult
from app.services.evaluation_service import EvaluationService
from app.services.job_service import RESULT_FIELDS
from app.services.target_client import TargetClient


def execute(payload: dict, index: int) -> dict:
    target = TargetApplication(**payload["target"])
    target.protected_values = [
        ProtectedValue(name="canary", value=v) for v in payload["protected_values"]
    ]
    definition = dict(payload["attacks"][index])
    definition["category"] = AttackCategory(definition["category"])
    definition["severity"] = Severity(definition["severity"])
    attack = AttackDefinition(**definition)
    result = TestResult()
    # No main database connection. Only the parent persists report evidence;
    # optional judging may use its separate disposable local cache.
    service = EvaluationService(
        None,
        target_client_factory=lambda _: None,
        judge_runtime=payload.get("judge_runtime", {"enabled": False}),
    )
    client = TargetClient(target, **payload["transport"])
    try:
        retryable = service._execute_attack(
            result,
            client,
            attack,
            target,
            payload["definitions"][index],
            payload["protected_values"]
            + [target.api_key or "", service.judge_runtime.get("api_key", "")],
        )
    finally:
        client.close()
    data = {name: getattr(result, name) for name in RESULT_FIELDS}
    return {"result": data, "retryable": retryable}


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        # Keep the attempt bounded even if the supervising worker is SIGKILLed.
        # This process leads its own session; kill its regex/schema descendants too.
        signal.signal(
            signal.SIGALRM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL)
        )
        signal.setitimer(signal.ITIMER_REAL, min(float(request["timeout"]), 60))
        output = execute(request["payload"], request["index"])
        print(json.dumps(output, allow_nan=False))
    except Exception:
        # No traceback can disclose input, credentials or target content.
        sys.exit(1)
