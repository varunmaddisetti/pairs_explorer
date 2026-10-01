"""Point-in-time pair detail, historical playback, explicit future reveal and 'what changed'."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import ResearchParams
from ..providers.base import Dataset
from .family import _panel, evaluate_family, labels_for, make_folds

BETA_SHIFT_WARN = 0.25       # relative change vs previous formation window
BETA_RANGE_WARN = 1.5        # max/min ratio across the last four windows


def _r(x, nd=6):
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def _list(a, nd=6):
    return [_r(v, nd) for v in a]


def resolve_as_of(ds: Dataset, as_of: str | None) -> pd.Timestamp:
    """Map a requested date to the last calendar session at or before it."""
    if not as_of:
        return ds.calendar[-1]
    t = pd.Timestamp(as_of)
    cal = ds.calendar[ds.calendar <= t]
    if not len(cal):
        raise ValueError(f"as-of {as_of} precedes the first available session")
    return cal[-1]


def family_row(ds: Dataset, a: str, b: str, as_of: pd.Timestamp, p: ResearchParams, diagnostics=False) -> tuple[dict, dict]:
    fam = evaluate_family(ds, as_of, p, diagnostics=diagnostics)
    row = next(r for r in fam["pairs"] if r["a"] == a and r["b"] == b)
    return row, fam["family"]


def beta_history(ds: Dataset, a: str, b: str, as_of: pd.Timestamp, p: ResearchParams) -> dict:
    """Betas from every prior fold formation window ending at or before as_of (plus as_of itself)."""
    from ..backtest.run import cached_fold_families
    folds = make_folds(len(ds.calendar), p)
    fams = cached_fold_families(ds, folds, p)
    hist = []
    for f in folds:
        end = ds.calendar[f.form_end]
        if end > as_of:
            break
        r = next(x for x in fams[f.k]["pairs"] if x["a"] == a and x["b"] == b)
        hist.append({"formation_end": end.strftime("%Y-%m-%d"), "fold": f.k, "beta": _r(r.get("beta")),
                     "coint_p": _r(r.get("coint_p")), "coint_p_adj": _r(r.get("coint_p_adj")),
                     "eligible": r["eligible"]})
    warnings = []
    betas = [h["beta"] for h in hist if h["beta"] is not None]
    if len(betas) >= 2 and betas[-2] != 0 and abs(betas[-1] / betas[-2] - 1) > BETA_SHIFT_WARN:
        warnings.append(f"beta moved {abs(betas[-1] / betas[-2] - 1):.0%} between the last two fold formation windows")
    last4 = betas[-4:]
    if len(last4) >= 2:
        if min(last4) <= 0 < max(last4):
            warnings.append("beta changed sign across recent formation windows")
        elif min(last4) > 0 and max(last4) / min(last4) > BETA_RANGE_WARN:
            warnings.append(f"beta ranged {min(last4):.2f}-{max(last4):.2f} across the last {len(last4)} windows")
    return {"history": hist, "warnings": warnings,
            "rule": f"explanatory heuristics: >{BETA_SHIFT_WARN:.0%} change between consecutive windows, sign change, "
                    f"or max/min ratio >{BETA_RANGE_WARN} over four windows. Not a structural-break test."}


def walk_forward_z(ds: Dataset, a: str, b: str, as_of: pd.Timestamp, p: ResearchParams) -> dict:
    """Out-of-sample z: each fold's frozen parameters applied to its own evaluation block, up to as_of."""
    from ..backtest.run import build_fold_specs
    specs, _ = build_fold_specs(ds, a, b, p, strict=False)
    dates, zs, folds = [], [], []
    for s in specs:
        for i in range(s.eval_start, s.eval_end + 1):
            if ds.calendar[i] > as_of:
                break
            dates.append(ds.calendar[i].strftime("%Y-%m-%d"))
            zs.append(_r(s.z[i], 4))
            folds.append(s.k)
    return {"dates": dates, "z": zs, "fold": folds}


def pair_detail(ds: Dataset, a: str, b: str, as_of: pd.Timestamp, p: ResearchParams) -> dict:
    a, b = sorted([a, b])
    if (a, b) not in {(x, y) for x, y, _ in ds.candidate_pairs()}:
        raise KeyError(f"{a}/{b} is not a predefined candidate pair")
    panel = _panel(ds, a, b).loc[:as_of]
    if panel.empty:
        raise ValueError("no observations at or before as-of")
    row, fam = family_row(ds, a, b, as_of, p, diagnostics=True)
    # descriptive (all history up to as_of; gaps disclosed, never filled)
    ca, cb = panel["close_a"], panel["close_b"]
    first_a = ca.dropna().iloc[0]
    first_b = cb.dropna().iloc[0]
    ra, rb = np.log(ca).diff(), np.log(cb).diff()
    roll = ra.rolling(p.rolling_corr_window, min_periods=p.rolling_corr_window).corr(rb)
    dd_a = ca / ca.cummax() - 1
    dd_b = cb / cb.cummax() - 1
    gaps = [d.strftime("%Y-%m-%d") for d in panel.index[~panel["complete"]]]
    descriptive = {
        "dates": [d.strftime("%Y-%m-%d") for d in panel.index],
        "norm_a": _list(ca / first_a * 100, 4), "norm_b": _list(cb / first_b * 100, 4),
        "ratio": _list(ca / cb, 6), "rolling_corr": _list(roll, 4),
        "drawdown_a": _list(dd_a, 4), "drawdown_b": _list(dd_b, 4),
        "full_period_return_corr": _r(ra.corr(rb), 4),
        "gaps": gaps,
        "note": "Descriptive views. Co-movement, a ratio or a correlation does not establish a stable spread "
                "or a tradeable relationship.",
    }
    formation = None
    if row["status"] == "tested":
        w = panel.iloc[-p.formation_window:]
        la, lb = np.log(w["close_a"].to_numpy()), np.log(w["close_b"].to_numpy())
        s = la - row["alpha"] - row["beta"] * lb
        z = (s - row["mu"]) / row["sigma"]
        formation = {
            "dates": [d.strftime("%Y-%m-%d") for d in w.index], "spread": _list(s), "z": _list(z, 4),
            "calibration_start": w.index[-p.calibration_window].strftime("%Y-%m-%d"),
            "bands": {"entry": p.entry_z, "exit": p.exit_z, "adverse": p.adverse_z},
        }
    bh = beta_history(ds, a, b, as_of, p)
    det = {
        "pair": f"{a}/{b}", "a": a, "b": b, "as_of": as_of.strftime("%Y-%m-%d"),
        "source_mode": ds.mode, "dataset_id": ds.dataset_id, "group": row["group"],
        "stats": row, "family": fam, "labels": labels_for(row, ds, p),
        "descriptive": descriptive, "formation": formation, "beta_history": bh,
        "walk_forward": walk_forward_z(ds, a, b, as_of, p),
        "available_until": ds.calendar[-1].strftime("%Y-%m-%d"),
    }
    from ..explanations.template import explain, what_changed
    prior_idx = ds.calendar.get_loc(as_of) - 21
    prior = None
    if prior_idx >= 0:
        prior_date = ds.calendar[prior_idx]
        prior_row, _ = family_row(ds, a, b, prior_date, p)
        prior = {"as_of": prior_date.strftime("%Y-%m-%d"), "stats": prior_row}
    det["explanation"] = explain(det, p)
    det["what_changed"] = what_changed(prior, det, p)
    return det


def reveal(ds: Dataset, a: str, b: str, as_of: pd.Timestamp, p: ResearchParams, horizon: int = 63) -> dict:
    """Explicit future reveal: as-of frozen parameters applied to the next `horizon` sessions."""
    a, b = sorted([a, b])
    row, _ = family_row(ds, a, b, as_of, p)
    full = _panel(ds, a, b)
    fut = full.loc[full.index > as_of].iloc[:horizon]
    out = {"pair": f"{a}/{b}", "as_of": as_of.strftime("%Y-%m-%d"), "horizon_requested": horizon,
           "sessions_available": int(len(fut)),
           "note": "FUTURE OUTCOME - revealed after the as-of state. Parameters were frozen at the as-of date; "
                   "nothing here was available when the as-of statistics were computed."}
    if row["status"] != "tested" or fut.empty:
        return out | {"available": False, "reason": row.get("skip_reason") or "no later observations available"}
    la, lb = np.log(fut["close_a"].to_numpy()), np.log(fut["close_b"].to_numpy())
    z = (la - row["alpha"] - row["beta"] * lb - row["mu"]) / row["sigma"]
    z0 = row["z_last"]
    dates = [d.strftime("%Y-%m-%d") for d in fut.index]
    cross = None
    crossing_note = None
    if abs(z0) <= p.exit_z:
        crossing_note = f"as-of z already inside the +/-{p.exit_z:g} exit band; no crossing to measure"
    for d, v in zip(dates if crossing_note is None else [], z):
        if np.isfinite(v) and ((z0 > 0 and v <= p.exit_z) or (z0 < 0 and v >= -p.exit_z)):
            cross = d
            break
    fin = z[np.isfinite(z)]
    adverse = None
    if len(fin):
        adverse = float(fin.max()) if z0 > 0 else float(fin.min())
    hit_adverse = bool(len(fin) and ((z0 > 0 and fin.max() >= p.adverse_z) or (z0 < 0 and fin.min() <= -p.adverse_z)))
    out |= {"available": True, "dates": dates, "z": _list(z, 4),
            "norm_a": _list(fut["close_a"] / full.loc[as_of, "close_a"] * 100, 4),
            "norm_b": _list(fut["close_b"] / full.loc[as_of, "close_b"] * 100, 4),
            "z_at_as_of": _r(z0, 4), "z_at_end": _r(z[-1], 4), "first_exit_band_crossing": cross,
            "crossing_note": crossing_note,
            "max_adverse_z": _r(adverse, 4), "hit_adverse_threshold": hit_adverse,
            "gaps": [d.strftime("%Y-%m-%d") for d in fut.index[~fut["complete"]]]}
    return out
