#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PYTHON="${SENTINEL_PYTHON:-$ROOT/.venv/bin/python}"

"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Sentinel checks require Python 3.12"'
"$PYTHON" -m pip check
"$PYTHON" -m ruff check backend demo_target scripts
"$PYTHON" -m ruff format --check backend demo_target scripts
# These services both import a package called app: use separate processes/cwds.
(cd backend && "$PYTHON" -m pytest)
(cd demo_target && "$PYTHON" -m pytest)
