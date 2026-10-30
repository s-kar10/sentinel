"""Durable queue consumer: python -m app.worker (one concurrent case per process)."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.database.migrations import require_current_schema
from app.database.session import SessionLocal, engine
from app.services.job_service import Claim, JobService, error_result


def stop_process(child):
    # Kill any remaining descendants even if the direct child already exited.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.communicate()


def execute_claim(claim: Claim, active) -> tuple[dict, bool] | None:
    deadline = time.monotonic() + claim.timeout
    child = subprocess.Popen(
        [sys.executable, "-m", "app.case_worker"],
        cwd=Path(__file__).resolve().parents[1],
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    data = json.dumps(
        {"payload": claim.payload, "index": claim.index, "timeout": claim.timeout}
    ).encode()
    try:
        while True:
            if not active():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return error_result("Case deadline exceeded."), True
            try:
                output, _ = child.communicate(input=data, timeout=min(0.5, remaining))
                if child.returncode != 0 or len(output) > 8_000_000:
                    return error_result("Case worker failed."), True
                decoded = json.loads(output)
                return decoded["result"], decoded["retryable"]
            except subprocess.TimeoutExpired:
                data = None
            except (ValueError, KeyError, TypeError):
                return error_result("Invalid case worker output."), True
    finally:
        stop_process(child)


def run_once(factory=SessionLocal, executor=execute_claim) -> bool:
    with factory() as db:
        claim = JobService(db).claim()
    if claim is None:
        return False

    def active():
        with factory() as db:
            return JobService(db).active(claim)

    output = executor(claim, active)
    if output is not None:
        result, retryable = output
        with factory() as db:
            JobService(db).finish(claim, result, retryable=retryable)
    return True


def main():
    require_current_schema(engine)

    def stop(_signal, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    while True:
        try:
            if not run_once():
                time.sleep(0.25)
        except Exception:
            # DB outage or unexpected dispatch failure: lease recovery handles it.
            print("Worker iteration failed; retrying in 2 seconds.", file=sys.stderr)
            time.sleep(2)


if __name__ == "__main__":
    main()
