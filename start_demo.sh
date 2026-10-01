#!/usr/bin/env bash
# One-command local demo (synthetic data, no keys). Uses uv if present, else a local .venv.
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  uv sync --python 3.12 --quiet
  exec uv run --python 3.12 python scripts/launcher.py "$@"
fi
if [ ! -x .venv/bin/python ]; then
  python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.lock
fi
exec .venv/bin/python scripts/launcher.py "$@"
