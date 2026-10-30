"""Bound expensive work in a killable subprocess, not a timeout-prone thread."""

import json
import os
import subprocess
import sys
from pathlib import Path

from app.evaluators.contracts import AssertionOutcome, Outcome, verdict

WORKER = Path(__file__).with_name("isolated_worker.py")


def isolated_check(task: dict, *, timeout: float = 1.0) -> AssertionOutcome:
    try:
        payload = json.dumps(task, allow_nan=False).encode("utf-8")
        if len(payload) > 1_000_000:
            return AssertionOutcome(Outcome.ERRORED, "evaluator_input_limit")
        result = subprocess.run(
            [sys.executable, "-I", str(WORKER)],
            input=payload,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={"PATH": os.defpath},
        )
        if result.returncode or len(result.stdout) > 1024:
            return AssertionOutcome(Outcome.ERRORED, "evaluator_worker_failed")
        response = json.loads(result.stdout)
        if type(response.get("passed")) is not bool:
            return AssertionOutcome(Outcome.ERRORED, "evaluator_worker_failed")
        evidence = (
            {"span": response["span"]} if response.get("span") is not None else {}
        )
        return verdict(response["passed"], "constraint_checked", **evidence)
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits for its child before raising.
        return AssertionOutcome(Outcome.ERRORED, "evaluator_timeout")
    except (OSError, ValueError, RecursionError):
        return AssertionOutcome(Outcome.ERRORED, "evaluator_worker_failed")
