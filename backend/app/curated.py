"""Curated teaching examples, selected algorithmically from development-period evidence.

Selection uses as-of statistics plus an explicit future reveal; it never reads the generator's
construction labels and never looks into the final holdout.
"""
from __future__ import annotations

import json

import numpy as np

from .analytics.family import evaluate_family, holdout_start_index
from .analytics.pair_detail import reveal
from .config import CACHE_DIR, ResearchParams, load_universe
from .providers.base import Dataset


def _dev_limit(ds: Dataset, p: ResearchParams) -> int:
    hs = holdout_start_index(len(ds.calendar), p)
    return (hs if hs is not None else len(ds.calendar)) - 63


def _scan(ds: Dataset, pair: tuple[str, str], p: ResearchParams, step: int):
    """Yield (date, as-of row, reveal) for dates in the development period where the pair is eligible."""
    a, b = pair
    for i in range(p.formation_window, _dev_limit(ds, p), step):
        d = ds.calendar[i]
        fam = evaluate_family(ds, d, p)
        r = next(x for x in fam["pairs"] if x["a"] == a and x["b"] == b)
        if not r["eligible"]:
            continue
        rv = reveal(ds, a, b, d, p)
        if rv.get("available"):
            yield d, r, rv


def mean_reverting_example(ds: Dataset, pair: tuple[str, str], p: ResearchParams, step: int = 2) -> dict | None:
    """First development as-of date where the pair is eligible, |z| >= entry, and the revealed z later
    crosses the direction-specific exit band without touching the adverse threshold first."""
    a, b = pair
    for d, r, rv in _scan(ds, pair, p, step):
        z0 = r["z_last"]
        if abs(z0) < p.entry_z or rv["first_exit_band_crossing"] is None:
            continue
        zs = rv["z"][: rv["dates"].index(rv["first_exit_band_crossing"]) + 1]
        if any(v is not None and abs(v) >= p.adverse_z for v in zs):
            continue
        n = len(zs)
        return {"kind": "mean_reverting", "a": a, "b": b, "as_of": d.strftime("%Y-%m-%d"),
                "summary": f"As of {d:%Y-%m-%d} the pair passed the screens (BY-adjusted p = {r['coint_p_adj']:.3f}) "
                           f"with z = {z0:+.2f}. Under those frozen parameters z crossed back inside the "
                           f"+/-{p.exit_z:g} band after {n} sessions (revealed outcome)."}
    return None


def failed_reversion_example(ds: Dataset, pair: tuple[str, str], p: ResearchParams, step: int = 4) -> dict | None:
    a, b = pair
    best = None
    for d, r, rv in _scan(ds, pair, p, step):
        z = np.array([v for v in rv["z"] if v is not None])
        worst = float(np.max(np.abs(z))) if len(z) else 0.0
        if worst >= p.adverse_z and (best is None or worst > best[0]):
            best = (worst, d, r, rv)
    if best is None:
        return None
    worst, d, r, rv = best
    return {"kind": "failed_reversion", "a": a, "b": b, "as_of": d.strftime("%Y-%m-%d"),
            "summary": f"As of {d:%Y-%m-%d} the pair passed the screens (BY-adjusted p = {r['coint_p_adj']:.3f}, "
                       f"z = {r['z_last']:+.2f}). Under those frozen parameters |z| reached {worst:.1f} within "
                       f"{rv['sessions_available']} sessions: the estimated relationship did not hold."}


def curated_examples(ds: Dataset, p: ResearchParams) -> dict:
    path = CACHE_DIR / ds.cache_namespace / f"curated_{p.hash()}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    out: dict = {"teaching": None, "contrast": None,
                 "note": "Selected from development-period as-of statistics and explicit reveals; "
                         "not from construction labels or the final holdout."}
    if ds.mode == "SYNTHETIC_DEMO":
        cur = load_universe("universe_synthetic.yaml").get("curated", {})
        if cur.get("teaching_pair"):
            out["teaching"] = mean_reverting_example(ds, tuple(sorted(cur["teaching_pair"])), p)
        if cur.get("contrast_pair"):
            out["contrast"] = failed_reversion_example(ds, tuple(sorted(cur["contrast_pair"])), p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
