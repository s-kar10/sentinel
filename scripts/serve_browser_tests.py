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


def require_free_ports(ports):
    """Reject live listeners, but allow released TIME_WAIT sockets like Uvicorn."""
    for port in ports:
        with socket.socket() as probe:
            # SO_REUSEADDR permits a sequential suite after TCP shutdown on Linux.
            # It does not permit binding over a live listener (no SO_REUSEPORT).
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))


def main():
    def stop(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    require_free_ports((18000, 18001))
    children = []
    with tempfile.TemporaryDirectory(prefix="sentinel-browser-") as directory:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                (
                    "DATABASE_",
                    "CORS_",
                    "TARGET_",
                    "SQL_",
                    "PYTHONPATH",
                    "AUTH_",
                    "APP_ENVIRONMENT",
                )
            )
        }
        env.update(
            AUTH_MODE="token"
            if os.environ.get("SENTINEL_BROWSER_AUTH") == "1"
            else "local",
            APP_ENVIRONMENT="development",
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
            if env["AUTH_MODE"] == "token":
                # Public fake credentials only for this fresh loopback test DB.
                # Never read, alter or provision a developer's configured database.
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        """
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.database.session import engine
from app.models.access import AccessToken
from app.auth.tokens import digest
with Session(engine) as db:
    for role, marker in [('admin', 'A'), ('reader', 'R')]:
        db.add(AccessToken(name='Browser ' + role, role=role,
            digest=digest('snt_' + marker * 43),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    db.commit()
""",
                    ],
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
