# Pairs Divergence Explorer - common commands. Requires uv (or a .venv) and Node for the UI build.
UV ?= uv
PY := $(UV) run --python 3.12
.PHONY: setup demo dev doctor test test-py test-ui build refresh generate check-start clean

setup:
	$(UV) sync --python 3.12
	cd frontend && npm ci --no-audit --no-fund

demo: ## start backend + built frontend in synthetic mode (no keys)
	$(PY) python scripts/launcher.py

dev: ## backend + Vite dev server
	$(PY) python scripts/launcher.py --dev

doctor:
	$(PY) python scripts/doctor.py

test: test-py test-ui

test-py:
	$(PY) python -m pytest tests

test-ui: build
	cd frontend && npx playwright test

build:
	cd frontend && npm run build
	$(PY) python -c "import sys; sys.path.insert(0,'backend'); import app.api.main; from app.config import load_default_params; load_default_params(); print('imports/config OK')"

refresh: ## explicit, bounded NSE MCP discovery + validation sample (no startup downloads)
	$(PY) python scripts/refresh.py

generate:
	$(PY) python scripts/generate_demo.py

check-start:
	$(PY) python scripts/launcher.py --check --port 8765

clean:
	rm -rf data/cache data/runtime frontend/dist frontend/test-results
