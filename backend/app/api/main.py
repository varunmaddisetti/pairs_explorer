"""FastAPI service. Backend numerical outputs are authoritative; the UI only renders them."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..analytics.family import scanner
from ..analytics.pair_detail import pair_detail, resolve_as_of, reveal
from ..backtest.run import run_pair_backtest
from ..card import render_card
from ..config import ROOT, SNAPSHOT_DIR, ResearchParams, load_default_params
from ..curated import curated_examples
from ..gate import DisplayNotPermitted, DisplayPolicy
from ..manifest import dependency_versions
from ..providers.base import Dataset, ProviderError
from ..providers.file import FileProvider
from ..providers.synthetic import SyntheticProvider
from ..registry import Registry
from ..validation.validate import DataValidationError

logging.basicConfig(level=os.environ.get("PDE_LOG_LEVEL", "INFO"),
                    format='{"t":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("pde.api")


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.source = os.environ.get("PDE_SOURCE", "synthetic")
        self.policy = DisplayPolicy.load()
        if self.source == "synthetic":
            self.provider = SyntheticProvider()
        elif self.source == "file":
            self.provider = FileProvider(os.environ.get("PDE_FILE_DATASET", ""))
        else:
            raise ProviderError(f"unknown PDE_SOURCE {self.source!r} (synthetic|file)")
        self.raw: Dataset = self.provider.load_dataset()
        self.ds: Dataset = self.policy.apply(self.raw)  # every endpoint uses the gated dataset
        self.params = load_default_params()
        self.registry = Registry()
        self.runs: OrderedDict[str, dict] = OrderedDict()

    def remember(self, run_id: str, result: dict) -> None:
        self.runs[run_id] = result
        while len(self.runs) > 16:
            self.runs.popitem(last=False)


_state: State | None = None


def state() -> State:
    global _state
    if _state is None:
        _state = State()
    return _state


def reset_state() -> None:
    global _state
    _state = None


app = FastAPI(title="Pairs Divergence Explorer", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.middleware("http")
async def timing(request: Request, call_next):
    t = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        log.info("%s %s %d %.0fms", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t) * 1000)
    return response


@app.exception_handler(DisplayNotPermitted)
async def _perm(_: Request, exc: DisplayNotPermitted):
    return JSONResponse({"error": "display_not_permitted", "detail": str(exc)}, status_code=403)


@app.exception_handler(DataValidationError)
async def _dv(_: Request, exc: DataValidationError):
    return JSONResponse({"error": "data_validation", "detail": str(exc)}, status_code=422)


def _pair(a: str, b: str) -> tuple[str, str]:
    ds = state().ds
    valid = {(x, y) for x, y, _ in ds.candidate_pairs()}
    a, b = sorted([a.upper(), b.upper()])
    if (a, b) not in valid:
        raise HTTPException(404, f"{a}/{b} is not a predefined same-industry candidate pair")
    return a, b


def _as_of(as_of: str | None) -> pd.Timestamp:
    try:
        return resolve_as_of(state().ds, as_of)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def _statuses(ds: Dataset, policy: DisplayPolicy) -> dict:
    return {"SYNTHETIC_DEMO": ds.mode == "SYNTHETIC_DEMO", "REAL_UNVALIDATED": ds.mode == "REAL_UNVALIDATED",
            "REAL_RESEARCH_VALIDATED": ds.mode == "REAL_RESEARCH_VALIDATED",
            "PUBLIC_DISPLAY_PERMITTED": bool(policy.public_display_permitted and ds.mode != "SYNTHETIC_DEMO")}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    st = state()
    ds = st.ds
    m = ds.manifest
    return {
        "mode": ds.mode, "statuses": _statuses(ds, st.policy), "source": st.source,
        "dataset_id": ds.dataset_id, "dataset_content_sha256": ds.content_hash,
        "first_date": ds.calendar[0].strftime("%Y-%m-%d"), "last_date": ds.calendar[-1].strftime("%Y-%m-%d"),
        "sessions": int(len(ds.calendar)), "calendar": ds.report.calendar,
        "symbols": ds.symbols, "groups": ds.groups, "universe_version": ds.universe_version,
        "candidate_pairs": [{"a": a, "b": b, "group": g} for a, b, g in ds.candidate_pairs()],
        "manifest": {k: m.get(k) for k in ("source", "vendor", "price_basis", "corporate_actions",
                                           "permitted_usage", "csv_sha256", "seed", "calendar", "validation_status",
                                           "retrieved_at", "timezone")},
        "display_policy": st.policy.to_dict(), "defaults": st.params.model_dump(),
        "params_hash": st.params.hash(),
    }


_CURATED_LOCK = threading.Lock()


def _curated() -> dict:
    st = state()
    with _CURATED_LOCK:
        return curated_examples(st.ds, st.params)


@app.on_event("startup")
def _warm() -> None:
    if os.environ.get("PDE_WARM", "1") == "1":
        threading.Thread(target=_curated, name="warm-curated", daemon=True).start()


@app.get("/api/curated")
def curated() -> dict:
    return _curated()


@app.get("/api/scanner")
def get_scanner(as_of: str | None = Query(None, max_length=10)) -> dict:
    st = state()
    t = _as_of(as_of)
    out = scanner(st.ds, t, st.params)
    out["mode"] = st.ds.mode
    return out


@app.get("/api/pair")
def get_pair(a: str = Query(..., max_length=24), b: str = Query(..., max_length=24),
             as_of: str | None = Query(None, max_length=10)) -> dict:
    a, b = _pair(a, b)
    return pair_detail(state().ds, a, b, _as_of(as_of), state().params)


@app.get("/api/reveal")
def get_reveal(a: str = Query(..., max_length=24), b: str = Query(..., max_length=24),
               as_of: str = Query(..., max_length=10), horizon: int = Query(63, ge=1, le=252)) -> dict:
    a, b = _pair(a, b)
    return reveal(state().ds, a, b, _as_of(as_of), state().params, horizon)


@app.get("/api/card.png")
def card(a: str = Query(..., max_length=24), b: str = Query(..., max_length=24),
         as_of: str | None = Query(None, max_length=10)) -> Response:
    a, b = _pair(a, b)
    det = pair_detail(state().ds, a, b, _as_of(as_of), state().params)
    png = render_card(det)
    name = f"pde_card_{a}_{b}_{det['as_of']}_{det['source_mode'].lower()}.png"
    return Response(png, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{name}"'})


class BacktestRequest(BaseModel):
    a: str = Field(..., max_length=24)
    b: str = Field(..., max_length=24)
    strict: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


EDITABLE = {"entry_z", "entry_z_max", "exit_z", "adverse_z", "max_holding", "cooldown_sessions",
            "commission_bps", "slippage_bps", "levy_bps", "borrow_annual", "gross_exposure",
            "starting_equity", "friction_mode"}


@app.post("/api/backtest")
def backtest(req: BacktestRequest) -> dict:
    st = state()
    a, b = _pair(req.a, req.b)
    bad = set(req.params) - EDITABLE
    if bad:
        raise HTTPException(400, f"parameters not editable in the UI: {sorted(bad)}")
    try:
        p = ResearchParams(**(st.params.model_dump() | req.params))
    except ValueError as exc:
        raise HTTPException(422, f"invalid parameters: {exc}") from None
    with st.lock:
        res = run_pair_backtest(st.ds, a, b, p, strict=req.strict)
    touches = res["holdout_start"] is not None
    run_id = st.registry.log("pair_backtest", res["pair"], res["manifest"], res["result_sha256"], touches)
    res["run_id"] = run_id
    res["registry"] = st.registry.summary() | {"recent": None}
    st.remember(run_id, res)
    return res


def _safe_cell(v: Any) -> Any:
    """CSV-injection guard: text starting with = + - @ is prefixed so spreadsheets do not evaluate it."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    keys = list(dict.fromkeys(k for r in rows for k in r))
    w = csv.DictWriter(buf, fieldnames=keys, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: _safe_cell(json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    return buf.getvalue()


@app.get("/api/backtest/{run_id}/bundle.zip")
def bundle(run_id: str) -> Response:
    st = state()
    if not run_id.isalnum() or len(run_id) > 32:
        raise HTTPException(400, "bad run id")
    res = st.runs.get(run_id)
    if res is None:
        man = st.registry.manifest(run_id)
        if man is None:
            raise HTTPException(404, "unknown run")
        if man["dataset_content_sha256"] != st.ds.content_hash:
            raise HTTPException(409, "run was made on a different dataset; cannot reproduce here")
        a, b = man["pair"].split("/")
        res = run_pair_backtest(st.ds, a, b, ResearchParams(**man["params"]), strict=man["strict"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", f"{res['result_label']}\nPair {res['pair']} | mode {res['manifest']['source_mode']}\n"
                   f"{res['experiment_class']}\nResult sha256 (timestamps stripped): {res['result_sha256']}\n"
                   "Reproduce: POST /api/backtest with params.json, or scripts/reproduce_run.py manifest.json\n")
        z.writestr("manifest.json", json.dumps(res["manifest"], indent=2, default=str))
        z.writestr("params.json", json.dumps(res["manifest"]["params"], indent=2))
        z.writestr("metrics.json", json.dumps({"metrics": res["metrics"], "status": res["status"],
                                               "stress": res.get("stress"), "assumptions": res["assumptions"]},
                                              indent=2, default=str))
        z.writestr("folds.csv", _csv(res["folds"]))
        z.writestr("trades.csv", _csv(res["trades"]))
        z.writestr("fills.csv", _csv(res["fills"]))
        z.writestr("daily_ledger.csv", _csv(res["daily"]))
        z.writestr("decisions.csv", _csv(res["decisions"]))
        z.writestr("events.csv", _csv(res["events"]))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="pde_backtest_{run_id}.zip"'})


@app.get("/api/diagnostics")
def diagnostics() -> dict:
    st = state()
    snaps = {}
    for p in sorted(SNAPSHOT_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            snaps[p.name] = {k: d.get(k) for k in ("status", "checked_at", "retrieved_at", "n_tools",
                                                   "schema_sha256", "endpoints", "url")}
        except json.JSONDecodeError:
            snaps[p.name] = {"error": "unreadable"}
    log_path = SNAPSHOT_DIR / "refresh_log.jsonl"
    attempts = log_path.read_text(encoding="utf-8").splitlines()[-10:] if log_path.exists() else []
    return {
        "active_provider": st.provider.health(), "data_quality": st.raw.report.to_dict(),
        "cache_namespace": st.ds.cache_namespace,
        "nse_mcp": {"snapshots": snaps, "recent_refresh_attempts": [json.loads(x) for x in attempts if x.strip()],
                    "status_note": "See REAL_DATA_READINESS.md. No NSE data has been validated in this build."},
        "dependency_versions": dependency_versions(),
    }


@app.get("/api/experiments")
def experiments() -> dict:
    return state().registry.summary()


# ---------------------------------------------------------------- static frontend
DIST = Path(os.environ.get("PDE_FRONTEND_DIST", ROOT / "frontend" / "dist"))
if (DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api"):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        if path and DIST.resolve() in f.parents and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
