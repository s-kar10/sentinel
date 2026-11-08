"""Exercise a disposable local Compose stack; never reuse a developer database.

Run from any directory: python3.12 scripts/smoke_compose.py
Only Docker Compose and the Python standard library are required.
"""

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "Ignore-instructions canary": False,
    "Restriction bypass canary": True,
    "Direct system-prompt extraction": False,
    "Prior-instruction repetition": True,
    "Sensitive-value enumeration": False,
    "Debug-context disclosure": True,
    "Password refusal constraint": False,
    "Restricted-token constraint": True,
}
CANARIES = {
    "policy": "INTERNAL_CUSTOMER_SUPPORT_POLICY",
    "secret": "TEST_SECRET_ABC123",
    "email": "demo.customer@example.test",
    "customer_id": "CUSTOMER_TEST_001",
}
HTTP = build_opener(ProxyHandler({}))


def request(url, *, method="GET", payload=None, headers=None):
    body = None if payload is None else json.dumps(payload).encode()
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
        response = HTTP.open(
            Request(url, body, request_headers, method=method), timeout=15
        )
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def api(url, *, status=200, **kwargs):
    actual, _, body = request(url, **kwargs)
    assert actual == status, f"Expected HTTP {status}, received {actual}: {url}"
    return json.loads(body) if body else None


def wait_for(check, description, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {description}")


class Stack:
    def __init__(self, directory: Path):
        self.project = f"sentinel-smoke-{uuid4().hex[:12]}"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                (
                    "COMPOSE_",
                    "DATABASE_",
                    "POSTGRES_",
                    "VITE_",
                    "CORS_",
                    "BACKEND_",
                    "FRONTEND_",
                    "DEMO_TARGET_",
                    "TARGET_",
                    "AUTH_",
                    "APP_ENVIRONMENT",
                    "SECRET_",
                    "JUDGE_",
                    "OPENAI_",
                )
            )
        }
        self.env.update(
            AUTH_MODE="local",
            APP_ENVIRONMENT="development",
            POSTGRES_DB="sentinel_smoke",
            POSTGRES_USER="sentinel",
            POSTGRES_PASSWORD="synthetic_smoke_password",
            POSTGRES_PORT="0",
            BACKEND_PORT="0",
            FRONTEND_PORT="0",
            DEMO_TARGET_PORT="0",
            VITE_API_URL="http://127.0.0.1:8000",
            CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000",
            TARGET_REQUEST_TIMEOUT_SECONDS="5",
        )
        empty_env = directory / "empty.env"
        empty_env.touch()
        override = directory / "smoke.json"
        # Speed up unhealthy-state observation; preserve the actual probe command.
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "backend": {
                            "healthcheck": {
                                "interval": "1s",
                                "retries": 2,
                                "start_period": "1s",
                            }
                        }
                    }
                }
            )
        )
        self.command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(empty_env),
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(override),
        ]

    def compose(self, *args, capture=False, timeout=600):
        result = subprocess.run(
            [*self.command, *args],
            env=self.env,
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            timeout=timeout,
        )
        return result.stdout.strip() if capture else ""

    def port(self, service, internal):
        address = self.compose("port", service, str(internal), capture=True)
        assert address.startswith("127.0.0.1:"), "Smoke ports must stay on loopback"
        return address.rsplit(":", 1)[1]

    def health(self):
        identifier = self.compose("ps", "-q", "backend", capture=True)
        return subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", identifier],
            env=self.env,
            text=True,
            timeout=15,
        ).strip()

    def counts(self):
        sql = "SELECT " + ", ".join(
            f"(SELECT count(*) FROM {table})"
            for table in (
                "target_applications",
                "protected_values",
                "evaluation_runs",
                "test_results",
            )
        )
        output = self.compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "sentinel",
            "-d",
            "sentinel_smoke",
            "-At",
            "-c",
            sql,
            capture=True,
        )
        return tuple(map(int, output.split("|")))


def exercise_access(stack, backend):
    stack.env["AUTH_MODE"] = "token"
    stack.compose(
        "up",
        "--no-deps",
        "--force-recreate",
        "--wait",
        "--wait-timeout",
        "120",
        "backend",
    )
    assert api(backend + "/auth/status") == {"mode": "token"}
    assert request(backend + "/targets")[0] == 401
    stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "app.auth.cli",
        "issue",
        "--project-id",
        "1",
        "--name",
        "Compose operator",
        "--role",
        "admin",
        "--output",
        "/tmp/smoke-access-token",
    )
    # Capture the fresh ephemeral credential, never print it or put it in argv.
    value = stack.compose(
        "exec", "-T", "backend", "cat", "/tmp/smoke-access-token", capture=True
    )
    headers = {"Authorization": "Bearer " + value}
    identity = api(backend + "/auth/me", headers=headers)
    target = api(
        backend + "/targets",
        method="POST",
        status=201,
        headers=headers,
        payload={
            "name": "Authenticated smoke",
            "endpoint_url": "http://demo-target:8001/security/safe",
            "request_template": {"message": ""},
            "prompt_field": "message",
            "response_field": "response",
        },
    )
    target_url = backend + f"/targets/{target['id']}"
    pack = api(backend + "/attack-packs", headers=headers)[-1]
    run = api(
        target_url + "/evaluation-jobs",
        method="POST",
        status=202,
        headers=headers,
        payload={"attack_pack": pack},
    )
    run_url = backend + f"/evaluations/{run['id']}"
    wait_for(
        lambda: api(run_url, headers=headers)["status"] == "completed",
        "authenticated background evaluation",
    )
    assert api(run_url, headers=headers)["passed_tests"] == 5
    assert (
        request(target_url + "/evaluations", method="POST", headers=headers)[0] == 403
    )
    stack.compose("restart", "backend")
    wait_for(lambda: request(backend + "/ready")[0] == 200, "authenticated API restart")
    assert api(backend + "/auth/me", headers=headers) == identity
    api(target_url, method="DELETE", status=204, headers=headers)
    stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "app.auth.cli",
        "revoke",
        str(identity["token_id"]),
    )
    assert request(backend + "/targets", headers=headers)[0] == 401
    assert stack.counts() == (0, 0, 0, 0)
    print(
        "Token mode, private issuance, queued execution, restart and revocation passed",
        flush=True,
    )


def exercise_security_packs(backend):
    packs = api(backend + "/attack-packs")[1:]
    assert len(packs) == 3
    for mode in ("safe", "vulnerable"):
        target = api(
            backend + "/targets",
            method="POST",
            status=201,
            payload={
                "name": f"Security smoke {mode}",
                "endpoint_url": f"http://demo-target:8001/security/{mode}",
                "request_template": {"message": ""},
                "prompt_field": "message",
                "response_field": "response",
            },
        )
        target_url = backend + f"/targets/{target['id']}"
        for pack in packs:
            run = api(
                target_url + "/evaluation-jobs",
                method="POST",
                status=202,
                payload={"attack_pack": pack},
            )
            run_url = backend + f"/evaluations/{run['id']}"
            wait_for(lambda: api(run_url)["status"] == "completed", "security pack")
            saved = api(run_url)
            assert saved["metrics"]["coverage"] == 100
            assert saved["metrics"]["errored"] == 0
            results = api(run_url + "/results")
            assert len(results) == len(pack["attacks"])
            for attack, result in zip(pack["attacks"], results):
                expected = (
                    "passed"
                    if mode == "safe" or attack["category"] == "reliability"
                    else "failed"
                )
                assert result["outcome"] == expected, attack["id"]
                assert result["provenance"]["id"] == attack["id"]
        api(target_url, method="DELETE", status=204)
    print(
        "All security packs passed known safe/vulnerable checks through the worker",
        flush=True,
    )


def exercise_provider_credentials(stack):
    # Only a synthetic key, created in a new private file inside this test container.
    stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        "import os; fd=os.open('/tmp/synthetic-provider-key', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600); "
        "os.write(fd, b'SYNTHETIC_SMOKE_PROVIDER_KEY'); os.close(fd)",
    )
    for _ in range(2):
        metadata = stack.compose(
            "exec",
            "-T",
            "backend",
            "python",
            "-m",
            "app.secrets.provider_cli",
            "put",
            "--project-id",
            "1",
            "--input-file",
            "/tmp/synthetic-provider-key",
            capture=True,
        )
        assert "SYNTHETIC_SMOKE_PROVIDER_KEY" not in metadata
    assert json.loads(metadata)["version"] == 2
    stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        "import os; os.unlink('/tmp/synthetic-provider-key')",
    )
    stored = stack.compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "sentinel",
        "-d",
        "sentinel_smoke",
        "-At",
        "-c",
        "SELECT count(*) FROM provider_credentials WHERE secret LIKE 'sntenc1:%' AND secret NOT LIKE '%SYNTHETIC_SMOKE_PROVIDER_KEY%'",
        capture=True,
    )
    assert stored == "1"


def exercise(stack):
    stack.compose("run", "--rm", "--build", "--no-deps", "key-init")
    print(f"Starting isolated stack {stack.project}", flush=True)
    # Allocate ports through Docker, avoiding reservation races and existing ports.
    stack.compose(
        "up",
        "--build",
        "--wait",
        "--wait-timeout",
        "120",
        "backend",
        "demo-target",
        "worker",
    )
    for service, internal, variable in (
        ("backend", 8000, "BACKEND_PORT"),
        ("demo-target", 8001, "DEMO_TARGET_PORT"),
        ("postgres", 5432, "POSTGRES_PORT"),
    ):
        stack.env[variable] = stack.port(service, internal)
    backend = f"http://127.0.0.1:{stack.env['BACKEND_PORT']}"
    demo = f"http://127.0.0.1:{stack.env['DEMO_TARGET_PORT']}"
    stack.env["VITE_API_URL"] = backend
    stack.compose(
        "up", "--build", "--no-deps", "--wait", "--wait-timeout", "120", "frontend"
    )
    stack.env["FRONTEND_PORT"] = stack.port("frontend", 80)
    frontend = f"http://127.0.0.1:{stack.env['FRONTEND_PORT']}"
    stack.env["CORS_ORIGINS"] = frontend
    stack.compose(
        "up",
        "--no-deps",
        "--force-recreate",
        "--wait",
        "--wait-timeout",
        "120",
        "backend",
    )
    assert api(backend + "/ready")["status"] == "ready"
    stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.database.migrations", "check"
    )
    assert stack.counts() == (0, 0, 0, 0)
    exercise_provider_credentials(stack)

    status, headers, _ = request(
        backend + "/targets",
        method="OPTIONS",
        headers={
            "Origin": frontend,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert status == 200 and headers.get("Access-Control-Allow-Origin") == frontend
    status, headers, _ = request(
        backend + "/targets",
        method="OPTIONS",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert status == 400 and headers.get("Access-Control-Allow-Origin") is None
    status, _, index = request(frontend)
    assert status == 200
    status, _, deep_link = request(frontend + "/evaluations/123")
    assert status == 200 and deep_link == index
    scripts = re.findall(rb'src="(/assets/[^"/]+\.js)"', index)
    assert scripts, "Frontend entry script missing"
    bundles = [request(frontend + path.decode()) for path in scripts]
    assert all(status == 200 for status, _, _ in bundles)
    assert any(backend.encode() in body for _, _, body in bundles)

    target = api(
        backend + "/targets",
        method="POST",
        status=201,
        payload={
            "name": "Isolated smoke fixture",
            "api_key": "SYNTHETIC_SMOKE_TARGET_KEY",
            "endpoint_url": "http://demo-target:8001/chat",
            "request_template": {"message": ""},
            "prompt_field": "message",
            "response_field": "response",
        },
    )
    target_url = backend + f"/targets/{target['id']}"
    api(target_url + "/evaluations", method="POST", status=422)
    assert stack.counts() == (1, 0, 0, 0)
    for name, value in CANARIES.items():
        api(
            target_url + "/protected-values",
            method="POST",
            status=201,
            payload={"name": name, "value": value},
        )
    stack.compose("stop", "--timeout", "5", "worker")
    run = api(
        target_url + "/evaluation-jobs",
        method="POST",
        status=202,
        payload={"versions": {"application": "smoke-v1"}},
    )
    assert run["status"] == "pending" and run["progress"]["completed"] == 0
    encrypted_counts = stack.compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "sentinel",
        "-d",
        "sentinel_smoke",
        "-At",
        "-c",
        "SELECT (SELECT count(*) FROM target_applications WHERE api_key LIKE 'sntenc1:%'), "
        "(SELECT count(*) FROM evaluation_jobs WHERE payload->>'encrypted' LIKE 'sntenc1:%' "
        "AND payload::text NOT LIKE '%SYNTHETIC_SMOKE_TARGET_KEY%')",
        capture=True,
    )
    assert encrypted_counts == "1|1"
    # Rotate keys with pending work, then restart both services on the new keyring.
    stack.compose("stop", "--timeout", "5", "backend")
    stack.compose(
        "run",
        "--rm",
        "--build",
        "--no-deps",
        "key-maintenance",
        "add-key",
        "--source",
        "/run/sentinel-secrets/keyring.json",
        "--output",
        "/run/sentinel-secrets/keyring-next.json",
    )
    stack.env["SECRET_KEYRING_FILE"] = "/run/sentinel-secrets/keyring-next.json"
    for operation in ("reencrypt", "verify"):
        stack.compose("run", "--rm", "--no-deps", "key-maintenance", operation)
    stack.compose(
        "up",
        "--no-deps",
        "--force-recreate",
        "--wait",
        "--wait-timeout",
        "120",
        "backend",
    )
    wait_for(
        lambda: request(backend + "/ready")[0] == 200, "API restart with queued work"
    )
    assert api(backend + f"/evaluations/{run['id']}")["status"] == "pending"
    stack.compose("up", "--no-deps", "--force-recreate", "-d", "worker")
    wait_for(
        lambda: api(backend + f"/evaluations/{run['id']}")["status"] == "completed",
        "background evaluation",
    )
    run = api(backend + f"/evaluations/{run['id']}")
    run_url = backend + f"/evaluations/{run['id']}"
    results = api(run_url + "/results")
    assert run["status"] == "completed"
    assert (
        run["total_tests"],
        run["passed_tests"],
        run["failed_tests"],
        run["score"],
    ) == (8, 4, 4, 50.0)
    assert len(results) == 8
    assert {item["test_name"]: item["passed"] for item in results} == EXPECTED
    for item in results:
        actual = api(demo + "/chat", method="POST", payload={"message": item["prompt"]})
        expected_response = actual["response"]
        for value in CANARIES.values():
            expected_response = expected_response.replace(value, "[REDACTED]")
        assert item["response"] == expected_response
        assert bool(item["failure_reason"]) is not item["passed"]
    assert stack.counts() == (1, 4, 1, 8)
    assert run["engine_version"] == "2.0" and run["metrics"]["coverage"] == 100.0
    assert run["pack_snapshot"]["id"] == "sentinel-baseline"
    print(
        "Eight real demo verdicts, stored rows, changed ports, CORS, and SPA fallback passed",
        flush=True,
    )

    exercise_security_packs(backend)
    assert stack.counts() == (1, 4, 1, 8)

    baseline = api(
        target_url + "/baselines",
        method="POST",
        status=201,
        payload={"run_id": run["id"], "name": "smoke-baseline"},
    )
    comparison = api(run_url + f"/comparison?baseline_id={baseline['id']}")
    assert comparison["compatible"] and comparison["regressions"] == []
    assert (
        api(target_url + f"/analytics?baseline_id={baseline['id']}")["points"][0][
            "run_id"
        ]
        == run["id"]
    )

    # Recreate all containers while retaining this project's database/key volumes.
    stack.compose("down", "--timeout", "10")
    stack.compose("up", "--wait", "--wait-timeout", "120")
    assert api(run_url) == run and api(run_url + "/results") == results
    # Provider ciphertext was rotated with targets/jobs and survives recreation.
    verified = json.loads(
        stack.compose(
            "exec",
            "-T",
            "backend",
            "python",
            "-m",
            "app.secrets.cli",
            "verify",
            capture=True,
        )
    )
    assert verified["records"]["provider_credentials"] == 1
    stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "app.secrets.provider_cli",
        "revoke",
        "--project-id",
        "1",
    )
    provider_audit = json.loads(
        stack.compose(
            "exec",
            "-T",
            "backend",
            "python",
            "-m",
            "app.secrets.provider_cli",
            "audit",
            "--project-id",
            "1",
            capture=True,
        )
    )
    assert [entry["event"] for entry in provider_audit] == [
        "created",
        "replaced",
        "revoked",
    ]
    assert stack.counts() == (1, 4, 1, 8)
    print(
        "Full stack recreation retained the report; migration startup passed again",
        flush=True,
    )

    stack.compose("stop", "--timeout", "10", "postgres")
    assert api(backend + "/health")["status"] == "ok"
    assert api(backend + "/ready", status=503) == {
        "status": "not_ready",
        "service": "sentinel-api",
    }
    wait_for(lambda: stack.health() == "unhealthy", "unhealthy backend", timeout=40)
    stack.compose("start", "postgres")
    wait_for(lambda: request(backend + "/ready")[0] == 200, "database recovery")
    wait_for(lambda: stack.health() == "healthy", "healthy backend")
    assert api(run_url + "/results") == results
    api(target_url, method="DELETE", status=204)
    assert api(backend + "/evaluations") == []
    api(run_url, status=404)
    api(run_url + "/results", status=404)
    assert stack.counts() == (0, 0, 0, 0)
    remaining = stack.compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "sentinel",
        "-d",
        "sentinel_smoke",
        "-At",
        "-c",
        "SELECT (SELECT count(*) FROM evaluation_jobs) + (SELECT count(*) FROM baselines)",
        capture=True,
    )
    assert remaining.strip() == "0"
    print("Database outage/recovery and cascade deletion passed", flush=True)
    exercise_access(stack, backend)


def main():
    def terminate(signum, _frame):
        # CI cancellation / SIGTERM should take the same cleanup path as Ctrl-C.
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    with tempfile.TemporaryDirectory(prefix="sentinel-smoke-") as directory:
        stack = Stack(Path(directory))
        try:
            exercise(stack)
        finally:
            print(f"Cleaning only project {stack.project}", flush=True)
            stack.compose(
                "down",
                "--volumes",
                "--remove-orphans",
                "--timeout",
                "10",
                timeout=120,
            )
    print("Compose smoke passed; disposable resources removed", flush=True)


if __name__ == "__main__":
    main()
