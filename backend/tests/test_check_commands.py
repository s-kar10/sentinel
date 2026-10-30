"""Exercise the shared check command, including failures that must stop CI."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", [None, "lint", "format", "backend_test"])
def test_python_check_command_stops_on_failure(tmp_path: Path, failure: str | None):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "scripts").mkdir()
    shutil.copy2(root / "scripts/check-python.sh", tmp_path / "scripts/check-python.sh")
    shutil.copy2(root / "ruff.toml", tmp_path / "ruff.toml")
    for service in ("backend", "demo_target"):
        directory = tmp_path / service
        directory.mkdir()
        (directory / "app.py").write_text(f'NAME = "{service}"\n')
        (directory / "test_behavior.py").write_text(
            "from pathlib import Path\n\n"
            "from app import NAME\n\n\n"
            "def test_own_app():\n"
            '    Path("tests-ran").touch()\n'
            f'    assert NAME == "{service}"\n'
        )

    backend = tmp_path / "backend"
    if failure == "lint":
        (backend / "app.py").write_text("NAME = undefined_name\n")
    elif failure == "format":
        (backend / "app.py").write_text("NAME='backend'\n")
    elif failure == "backend_test":
        (backend / "app.py").write_text('NAME = "wrong-service"\n')

    result = subprocess.run(
        ["bash", str(tmp_path / "scripts/check-python.sh")],
        cwd=tmp_path,
        env={**os.environ, "SENTINEL_PYTHON": sys.executable},
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    if failure is None:
        assert result.returncode == 0, output
        assert (backend / "tests-ran").exists()
        assert (tmp_path / "demo_target/tests-ran").exists()
    else:
        assert result.returncode != 0, output
        assert not (tmp_path / "demo_target/tests-ran").exists()
        if failure == "backend_test":
            assert (backend / "tests-ran").exists()
            assert "AssertionError" in output
        else:
            assert not (backend / "tests-ran").exists()
            assert ("F821" if failure == "lint" else "Would reformat") in output
