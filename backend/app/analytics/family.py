"""Formation-window evaluation of a candidate family, folds and the as-of scanner.

Everything here is computed from observations dated at or before the formation end date.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import ResearchParams
from ..providers.base import Dataset
from .stats import engle_granger, fdr_by, fit_spread, half_life, unit_root_diagnostics


@dataclass(frozen=True)
class Fold:
    k: int
    form_start: int    # calendar index, inclusive
    form_end: int      # inclusive (last formation session)
    eval_start: int    # inclusive
    eval_end: int      # inclusive (scheduled boundary-exit session)
    segment: str       # "development" | "holdout"

    def to_dict(self, cal: pd.DatetimeIndex) -> dict:
        f = lambda i: cal[i].strftime("%Y-%m-%d")  # noqa: E731
        return {"k": self.k, "segment": self.segment,
                "formation_start": f(self.form_start), "formation_end": f(self.form_end),
                "evaluation_start": f(self.eval_start), "evaluation_end": f(self.eval_end),
                "evaluation_sessions": self.eval_end - self.eval_start + 1}


def holdout_start_index(n: int, p: ResearchParams) -> int | None:
    """First calendar index of the final holdout, if history is sufficient."""
    if p.final_holdout <= 0:
        return None
    start = n - p.final_holdout
    if start < p.formation_window + p.evaluation_block:  # need >=1 full development fold before it
        return None
    return start


def make_folds(n: int, p: ResearchParams) -> list[Fold]:
    folds: list[Fold] = []
    hs = holdout_start_index(n, p)
    k = 0
    eval_start = p.formation_window
    while eval_start < n:
        eval_end = min(eval_start + p.evaluation_block, n) - 1
        if eval_end - eval_start + 1 < 2:  # a 1-session block cannot hold a position
            break
        seg = "holdout" if hs is not None and eval_start >= hs else "development"
        folds.append(Fold(k, eval_start - p.formation_window, eval_start - 1, eval_start, eval_end, seg))
        k += 1
        eval_start += p.evaluation_block
    return folds


def _finite(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else x


def evaluate_pair_window(panel: pd.DataFrame, end_date: pd.Timestamp, p: ResearchParams,
                         diagnostics: bool = False) -> dict:
    """Fit/test one pair on the `formation_window` sessions ending at end_date (inclusive)."""
    w = panel.loc[:end_date].iloc[-p.formation_window:]
    res: dict = {"formation_end": end_date.strftime("%Y-%m-%d"), "n_obs": int(len(w))}
    if len(w) < p.formation_window:
        res.update(status="skipped", skip_reason=f"insufficient_history({len(w)}<{p.formation_window})")
        return res
    res["formation_start"] = w.index[0].strftime("%Y-%m-%d")
    if not w["complete"].all():
        miss = [d.strftime("%Y-%m-%d") for d in w.index[~w["complete"]]]
        res.update(status="skipped", skip_reason=f"missing_sessions_in_formation({len(miss)})", missing=miss[:20])
        return res
    la, lb = np.log(w["close_a"].to_numpy()), np.log(w["close_b"].to_numpy())
    model = fit_spread(la, lb, p.calibration_window, p.formation_window)
    if not model.valid:
        res.update(status="skipped", skip_reason=";".join(model.reasons))
        return res
    eg = engle_granger(la, lb)
    if not eg["valid"]:
        res.update(status="skipped", skip_reason=eg.get("invalid_reason", "invalid_test_statistic"))
        return res
    resid = model.spread(la, lb)
    z = (resid - model.mu) / model.sigma
    hl = half_life(resid)
    ra, rb = np.diff(la), np.diff(lb)
    corr = float(np.corrcoef(ra, rb)[0, 1]) if np.std(ra) > 0 and np.std(rb) > 0 else None
    res.update(
        status="tested", alpha=model.alpha, beta=model.beta, r2=model.r2, mu=model.mu, sigma=model.sigma,
        z_last=float(z[-1]), spread_last=float(resid[-1]),
        coint_stat=eg["statistic"], coint_p=eg["pvalue"], coint_crit_5pct=eg["crit_5pct"],
        coint_crit_1pct=eg["crit_1pct"], coint_crit_10pct=eg["crit_10pct"], coint_maxlag=eg["maxlag"],
        half_life=_finite(hl["half_life"]), hl_status=hl["status"], rho=_finite(hl["rho"]),
        return_corr=corr,
    )
    if diagnostics:
        res["unit_root"] = [unit_root_diagnostics(la, "log A"), unit_root_diagnostics(lb, "log B")]
    return res


def apply_family(results: list[dict], p: ResearchParams) -> dict:
    """Benjamini-Yekutieli across the tested members of one formation-date family + eligibility."""
    tested = [r for r in results if r["status"] == "tested"]
    reject, adj = fdr_by([r["coint_p"] for r in tested], p.fdr_alpha)
    for r, rej, a in zip(tested, reject, adj):
        r["coint_p_adj"] = a
        r["fdr_reject"] = rej
    for r in results:
        reasons: list[str] = []
        if r["status"] != "tested":
            reasons.append(r["skip_reason"])
        else:
            if not r["fdr_reject"]:
                reasons.append(f"no_cointegration_evidence_after_BY(adj_p={r['coint_p_adj']:.3f}>= {p.fdr_alpha})")
            if not (p.beta_min <= r["beta"] <= p.beta_max):
                reasons.append(f"beta_outside_[{p.beta_min},{p.beta_max}]({r['beta']:.3f})")
            if r["half_life"] is None:
                reasons.append(f"half_life_undefined({r['hl_status']})")
            elif not (p.half_life_min <= r["half_life"] <= p.half_life_max):
                reasons.append(f"half_life_outside_[{p.half_life_min:g},{p.half_life_max:g}]({r['half_life']:.1f})")
        r["eligible"] = not reasons
        r["exclusion_reasons"] = reasons
    return {
        "family_size": len(tested),
        "n_candidates": len(results),
        "n_skipped": len(results) - len(tested),
        "n_eligible": sum(r["eligible"] for r in results),
        "method": f"Benjamini-Yekutieli (fdr_by) at nominal {p.fdr_alpha}",
    }


def evaluate_family(ds: Dataset, end_date: pd.Timestamp, p: ResearchParams, diagnostics: bool = False) -> dict:
    results = []
    for a, b, group in ds.candidate_pairs():
        r = evaluate_pair_window(_panel(ds, a, b), end_date, p, diagnostics)
        r.update(a=a, b=b, group=group, pair=f"{a}/{b}")
        results.append(r)
    fam = apply_family(results, p)
    return {"formation_end": end_date.strftime("%Y-%m-%d"), "family": fam, "pairs": results}


_PANELS: dict[tuple, pd.DataFrame] = {}


def _panel(ds: Dataset, a: str, b: str) -> pd.DataFrame:
    key = (ds.uid, ds.content_hash, a, b, len(ds.calendar))
    if key not in _PANELS:
        if len(_PANELS) > 256:
            _PANELS.clear()
        _PANELS[key] = ds.panel(a, b)
    return _PANELS[key]


def scanner(ds: Dataset, as_of: pd.Timestamp, p: ResearchParams) -> dict:
    """As-of scanner: every statistic uses only the trailing formation window ending at as_of."""
    fam = evaluate_family(ds, as_of, p)
    rows = []
    for r in fam["pairs"]:
        panel = _panel(ds, r["a"], r["b"])
        last = panel.loc[:as_of]
        rows.append(r | {
            "last_observation": last.index[-1].strftime("%Y-%m-%d") if len(last) else None,
            "source_mode": ds.mode,
            "adjustment_status": sorted(ds.frame[ds.frame["symbol"].isin([r["a"], r["b"]])]["adjustment_status"].unique()),
            "labels": labels_for(r, ds, p),
        })
    eligible = sorted([r for r in rows if r["eligible"]], key=lambda r: -abs(r["z_last"]))
    excluded = [r for r in rows if not r["eligible"]]
    return {"as_of": as_of.strftime("%Y-%m-%d"), "family": fam["family"], "eligible": eligible,
            "excluded": excluded, "ranking": "descriptive: absolute z-score within eligible pairs"}


def labels_for(r: dict, ds: Dataset, p: ResearchParams) -> dict:
    """Four separate labels; no combined 'confidence' score."""
    if r["status"] != "tested":
        rel = "not tested"
    elif r.get("eligible"):
        rel = "evidence consistent with cointegration (BY-adjusted)"
    elif r.get("fdr_reject"):
        rel = "cointegration evidence, but outside beta/half-life screens"
    else:
        rel = "weak: no cointegration evidence after correction"
    z = r.get("z_last")
    if z is None:
        div = "n/a"
    else:
        az = abs(z)
        div = ("beyond adverse threshold" if az >= p.adverse_z else "large" if az >= p.entry_z
               else "moderate" if az >= 1.0 else "small")
    dq = "synthetic (validated generator)" if ds.mode == "SYNTHETIC_DEMO" else (
        "research-validated" if ds.mode == "REAL_RESEARCH_VALIDATED" else "real, NOT validated")
    if r["status"] != "tested" and "missing" in r.get("skip_reason", ""):
        dq = "missing sessions"
    exe = "hypothetical fractional long/short; borrow availability NOT VERIFIED"
    return {"relationship_evidence": rel, "observed_divergence": div, "data_quality": dq,
            "execution_assumptions": exe}


def fold_families(ds: Dataset, folds: list[Fold], p: ResearchParams) -> dict[int, dict]:
    """Family evaluation for every fold, using only that fold's formation window."""
    return {f.k: evaluate_family(ds, ds.calendar[f.form_end], p) for f in folds}
