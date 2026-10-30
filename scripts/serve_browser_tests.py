"""Run loopback-only API/demo processes against a temporary migrated SQLite DB."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    def stop(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    # Refuse occupied ports before starting either child; never reuse live apps.
    for port in (18000, 18001):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    children = []
    with tempfile.TemporaryDirectory(prefix="sentinel-browser-") as directory:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                ("DATABASE_", "CORS_", "TARGET_", "SQL_", "PYTHONPATH")
            )
        }
        env.update(
            DATABASE_URL=f"sqlite:///{directory}/test.db",
            CORS_ORIGINS="http://127.0.0.1:18473",
            PYTHONPATH=str(ROOT / "backend"),
            TARGET_REQUEST_TIMEOUT_SECONDS="2",
        )
        try:
            subprocess.run(
                [sys.executable, "-m", "app.database.migrations", "upgrade"],
                cwd=directory,
                env=env,
                check=True,
            )
            for service, port in (("demo_target", 18001), ("backend", 18000)):
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ],
                        cwd=directory,
                        env={**env, "PYTHONPATH": str(ROOT / service)},
                    )
                )
            children.append(
                subprocess.Popen(
                    [sys.executable, "-m", "app.worker"], cwd=directory, env=env
                )
            )
            while all(child.poll() is None for child in children):
                time.sleep(0.2)
            raise RuntimeError("Browser-test service exited unexpectedly")
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
            for child in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
