"""Bounded provider subprocess; secrets travel over stdin, never argv or logs."""

import json
import os
import signal
import sys

from app.judges.contracts import ProviderResult
from app.judges.providers import PROVIDERS


def execute(data):
    provider = PROVIDERS.get(data["provider"])
    if provider is None:
        return ProviderResult(error="judge_unknown_provider")
    return provider.evaluate(data["request"], data["runtime"])


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
        signal.setitimer(signal.ITIMER_REAL, min(float(data["runtime"]["timeout"]), 30))
        result = execute(data)
        print(result.model_dump_json())
    except Exception:
        sys.exit(1)
