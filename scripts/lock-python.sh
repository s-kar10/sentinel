#!/usr/bin/env bash
# Regenerate portable, hash-checked pip requirements from the service metadata.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_PYTHON:-$PWD/.venv/bin/python}"
MODE="${1:---check}"
if [[ "$MODE" != "--check" && "$MODE" != "--write" && "$MODE" != "--upgrade" ]]; then
  echo "Usage: bash scripts/lock-python.sh [--check|--write|--upgrade]" >&2
  exit 2
fi
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

compile() {
  local destination="$1"
  shift
  local candidate="$TEMP_DIR/$(echo "$destination" | tr / _)"
  if [[ "$MODE" == "--upgrade" ]]; then set -- "$@" --upgrade; fi
  # Reuse reviewed pins; new releases alone must not change an existing lock.
  if [[ -f "$destination" ]]; then cp "$destination" "$candidate"; fi
  "$PYTHON" -m uv pip compile --universal --python-version 3.12 \
    --generate-hashes --no-header --no-annotate --quiet \
    "$@" --output-file "$candidate"
  if [[ "$MODE" != "--check" ]]; then
    cp "$candidate" "$destination"
  elif ! cmp -s "$candidate" "$destination"; then
    echo "Stale lock: $destination. Run bash scripts/lock-python.sh --write and review the changes." >&2
    exit 1
  fi
}

compile backend/requirements.txt backend/pyproject.toml
compile backend/requirements-dev.txt backend/pyproject.toml --extra test \
  --constraint backend/requirements.txt
# Share compatible runtime versions between the demo and backend integration test.
compile demo_target/requirements.txt demo_target/pyproject.toml \
  --constraint backend/requirements.txt
compile demo_target/requirements-dev.txt demo_target/pyproject.toml --extra test \
  --constraint backend/requirements-dev.txt --constraint demo_target/requirements.txt
echo "Python locks $MODE: OK"
