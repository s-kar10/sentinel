"""Ensure the smoke harness cannot select or clean the developer's stack."""

import importlib.util
import signal
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("fail", [False, True])
def test_cleanup_is_scoped_even_on_failure(monkeypatch, fail):
    path = Path(__file__).resolve().parents[2] / "scripts/smoke_compose.py"
    spec = importlib.util.spec_from_file_location("compose_smoke", path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "developer-stack")
    monkeypatch.setenv("COMPOSE_FILE", "developer-override.yml")
    monkeypatch.setenv("POSTGRES_PASSWORD", "FAKE_PRIVATE_PASSWORD")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert command[:2] == ["docker", "compose"]
        project = command[command.index("--project-name") + 1]
        assert project.startswith("sentinel-smoke-")
        assert "developer-stack" not in command
        assert "COMPOSE_FILE" not in kwargs["env"]
        assert kwargs["env"]["POSTGRES_PASSWORD"] == "synthetic_smoke_password"
        assert Path(command[command.index("--env-file") + 1]).read_text() == ""
        return subprocess.CompletedProcess(command, 0)

    def exercise(stack):
        if fail:
            raise RuntimeError("Simulated failed smoke assertion")

    monkeypatch.setattr(smoke.subprocess, "run", run)
    monkeypatch.setattr(smoke, "exercise", exercise)
    previous = signal.getsignal(signal.SIGTERM)
    try:
        if fail:
            with pytest.raises(RuntimeError, match="Simulated failed smoke"):
                smoke.main()
        else:
            smoke.main()
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert len(commands) == 1
    assert commands[0][-5:] == [
        "down",
        "--volumes",
        "--remove-orphans",
        "--timeout",
        "10",
    ]
