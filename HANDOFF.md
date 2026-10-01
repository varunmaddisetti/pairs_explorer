# Handoff

* Branch: `claude/pairs-divergence-explorer-build-ytkdso`. The code commit with evidence is `fee3ed9`; later commits are documentation.
* State: all required phases complete for the synthetic scope; real-data scope blocked externally.

## Commands
```
uv sync --python 3.12 && (cd frontend && npm ci)   # setup
make demo            # http://127.0.0.1:8000 (or next free port)
make test            # 80 pytest + 4 Playwright
make doctor; make refresh
```

## Where things are
* Statistics: `backend/app/analytics/stats.py`, families/folds/scanner `family.py`, as-of detail/reveal `pair_detail.py`
* Backtest engine + ledger: `backend/app/backtest/engine.py`; runner/comparators `run.py`; metrics `metrics.py`
* Providers: `backend/app/providers/{synthetic,file,nse_mcp}.py`; validation `backend/app/validation/validate.py`
* Gate/permissions: `backend/app/gate.py`, `config/display_policy.yaml`
* UI: `frontend/src/views/*`

## Next concrete actions
1. In an environment that can reach `mcp.nseindia.in`: `make refresh`, inspect the snapshot, fill `config/nse_mapping.yaml` (REAL_DATA_READINESS steps 2–8).
2. Add a verified NSE holiday calendar file and use it in `validation.expected_calendar` for real data.
3. Optional (after gates): structural-break test (named, documented), optional explanation adapter, dark theme.
4. Verify `docker compose up --build` on a machine with a Docker daemon.

## Push status
`git push -u origin claude/pairs-divergence-explorer-build-ytkdso` was refused on 2026-10-01 (HTTP 403: the Claude GitHub App has no access to
`varunmaddisetti/pairs_explorer`). All commits exist only in the local clone of this session. After access is fixed, push the branch as-is.
