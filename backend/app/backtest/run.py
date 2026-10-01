"""Pair-sleeve backtest runner: fold specs, base run, comparators, stress scenarios and segments."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..analytics.family import Fold, fold_families, holdout_start_index, make_folds
from ..config import ResearchParams
from ..manifest import experiment_manifest, stable_hash
from ..providers.base import Dataset
from ..validation.validate import DataValidationError, assert_strategy_returns_allowed
from .engine import Costs, FoldSpec, Ledger, simulate_sleeve
from .metrics import equity_metrics, trade_metrics

_FAMILY_CACHE: dict[tuple, dict] = {}


def cached_fold_families(ds: Dataset, folds: list[Fold], p: ResearchParams) -> dict[int, dict]:
    key = (ds.cache_namespace, len(ds.calendar), p.hash(), ds.uid)
    if key not in _FAMILY_CACHE:
        if len(_FAMILY_CACHE) > 32:
            _FAMILY_CACHE.clear()
        _FAMILY_CACHE[key] = fold_families(ds, folds, p)
    return _FAMILY_CACHE[key]


def pair_arrays(ds: Dataset, a: str, b: str) -> dict[str, np.ndarray]:
    panel = ds.panel(a, b).reindex(ds.calendar)
    return {c: panel[c].to_numpy(dtype=float) for c in ("open_a", "close_a", "open_b", "close_b")}


def build_fold_specs(ds: Dataset, a: str, b: str, p: ResearchParams, strict: bool = True,
                     folds: list[Fold] | None = None, families: dict | None = None) -> tuple[list[FoldSpec], list[dict]]:
    folds = folds or make_folds(len(ds.calendar), p)
    families = families or cached_fold_families(ds, folds, p)
    arr = pair_arrays(ds, a, b)
    la, lb = np.log(arr["close_a"]), np.log(arr["close_b"])
    specs, table = [], []
    for f in folds:
        fam = families[f.k]
        r = next(x for x in fam["pairs"] if x["a"] == a and x["b"] == b)
        reasons = list(r["exclusion_reasons"])
        win = slice(f.eval_start, f.eval_end + 1)
        complete = bool(np.isfinite(arr["open_a"][win]).all() and np.isfinite(arr["close_a"][win]).all()
                        and np.isfinite(arr["open_b"][win]).all() and np.isfinite(arr["close_b"][win]).all())
        if strict and not complete:
            reasons.append("missing_sessions_in_evaluation_block(strict)")
        tradable = not reasons
        z = np.full(len(ds.calendar), np.nan)
        if r["status"] == "tested":
            idx = slice(f.form_end, f.eval_end + 1)
            with np.errstate(invalid="ignore"):
                z[idx] = (la[idx] - r["alpha"] - r["beta"] * lb[idx] - r["mu"]) / r["sigma"]
        specs.append(FoldSpec(f.k, f.form_end, f.eval_start, f.eval_end, f.segment, tradable,
                              r.get("beta"), z, reasons))
        table.append(f.to_dict(ds.calendar) | {
            "tradable": tradable, "exclusion_reasons": reasons, "family_size": fam["family"]["family_size"],
            "family_skipped": fam["family"]["n_skipped"], "beta": r.get("beta"), "alpha": r.get("alpha"),
            "mu": r.get("mu"), "sigma": r.get("sigma"), "coint_p": r.get("coint_p"),
            "coint_p_adj": r.get("coint_p_adj"), "half_life": r.get("half_life"),
            "z_at_formation_end": r.get("z_last"), "eval_block_complete": complete})
    return specs, table


def _long_only(ds: Dataset, a: str, b: str, arr: dict, first: int, last: int, p: ResearchParams,
               costs: Costs) -> list[float]:
    """Comparator: 45%/45% of equity long A and long B at the first evaluation open, held to the
    final close, same execution-cost convention; no shorting, no borrow."""
    led = Ledger(p.starting_equity, a, b)
    g = p.gross_exposure * p.starting_equity
    oa, ob = arr["open_a"][first], arr["open_b"][first]
    led.trade("A", g / 2 / (oa * (1 + costs.slip_rate)), oa, costs, ds.calendar[first], "open", "entry")
    led.trade("B", g / 2 / (ob * (1 + costs.slip_rate)), ob, costs, ds.calendar[first], "open", "entry")
    eq = []
    for i in range(first, last + 1):
        ca, cb = arr["close_a"][i], arr["close_b"][i]
        if not (np.isfinite(ca) and np.isfinite(cb)):
            eq.append(eq[-1] if eq else p.starting_equity)  # display only; flagged via data quality
            continue
        if i == last:
            led.trade("A", -led.q["A"], ca, costs, ds.calendar[i], "close", "end")
            led.trade("B", -led.q["B"], cb, costs, ds.calendar[i], "close", "end")
            eq.append(led.cash)
        else:
            eq.append(led.equity(ca, cb))
    return eq


def _segments(daily: list[dict], p: ResearchParams, holdout_date: str | None) -> dict:
    out = {}
    eq = [d["equity"] for d in daily]
    dates = [d["date"] for d in daily]
    out["all_evaluation"] = equity_metrics(eq, p.starting_equity)
    if holdout_date is not None and holdout_date in dates:
        h = dates.index(holdout_date)
        out["development"] = equity_metrics(eq[:h], p.starting_equity)
        start = eq[h - 1] if h > 0 else p.starting_equity
        out["final_holdout"] = equity_metrics(eq[h:], start)
    else:
        out["development"] = out["all_evaluation"]
        out["final_holdout"] = None
    return out


def run_pair_backtest(ds: Dataset, a: str, b: str, p: ResearchParams, strict: bool = True,
                      include_comparators: bool = True) -> dict:
    a, b = sorted([a, b])
    if (a, b) not in {(x, y) for x, y, _ in ds.candidate_pairs()}:
        raise KeyError(f"{a}/{b} is not a predefined same-industry candidate pair")
    folds = make_folds(len(ds.calendar), p)
    if not folds:
        raise ValueError("insufficient history for a single formation + evaluation fold")
    families = cached_fold_families(ds, folds, p)
    specs, fold_table = build_fold_specs(ds, a, b, p, strict, folds, families)
    arr = pair_arrays(ds, a, b)
    costs = Costs.from_params(p)

    def sim(c: Costs) -> dict:
        return simulate_sleeve(ds.calendar, arr["open_a"], arr["close_a"], arr["open_b"], arr["close_b"],
                               specs, p, c, a, b)

    base = sim(costs)
    peak = p.starting_equity
    for row in base["daily"]:
        peak = max(peak, row["equity"])
        row["drawdown"] = row["equity"] / peak - 1 if peak > 0 else None
    hs = holdout_start_index(len(ds.calendar), p)
    holdout_date = ds.calendar[hs].strftime("%Y-%m-%d") if hs is not None else None
    mean_eq = float(np.mean([d["equity"] for d in base["daily"]])) if base["daily"] else None

    adj = set(ds.frame[ds.frame["symbol"].isin([a, b])]["adjustment_status"].unique())
    try:
        assert_strategy_returns_allowed(ds.mode, adj, ds.corporate_actions_accounted)
        result_label = "HYPOTHETICAL SIMULATION ON SYNTHETIC DATA" if ds.mode == "SYNTHETIC_DEMO" \
            else "HYPOTHETICAL SIMULATION (research-validated data scope)"
    except DataValidationError as exc:
        result_label = f"PRICE-ONLY DIAGNOSTIC - not a validated strategy return ({exc})"

    non_default = p.differs_from_defaults()
    out = {
        "pair": f"{a}/{b}", "a": a, "b": b, "strict": strict, "result_label": result_label,
        "experiment_class": "exploratory (non-default parameters: " + ", ".join(non_default) + ")"
        if non_default else "pre-specified defaults",
        "holdout_start": holdout_date,
        "holdout_note": "Final holdout = last %d sessions. Parameters and methodology were fixed before it; "
                        "any rerun with changed settings is exploratory and logged." % p.final_holdout,
        "folds": fold_table,
        "trades": base["trades"], "fills": base["fills"], "daily": base["daily"],
        "decisions": base["decisions"], "events": base["events"], "status": base["status"],
        "open_trade": base["open_trade"], "totals": base["totals"],
        "metrics": {"segments": _segments(base["daily"], p, holdout_date),
                    "trades": trade_metrics(base["trades"], base["totals"]["traded_notional"], mean_eq),
                    "costs": {"fees": base["totals"]["fees"], "slippage_cost_in_prices": base["totals"]["slippage_cost"],
                              "borrow": base["totals"]["borrow"],
                              "total": base["totals"]["fees"] + base["totals"]["slippage_cost"] + base["totals"]["borrow"]}},
        "assumptions": {
            "friction_mode": p.friction_mode, "commission_bps": p.commission_bps, "slippage_bps": p.slippage_bps,
            "levy_bps": p.levy_bps, "borrow_annual": p.borrow_annual, "cash_interest_annual": 0.0,
            "risk_free_annual": 0.0, "gross_exposure": p.gross_exposure, "starting_equity": p.starting_equity,
            "fractional_shares": True,
            "borrow_availability": "NOT VERIFIED - hypothetical cash-equity long/short",
            "fees_note": "generic scenarios, not verified Indian broker tariffs",
        },
    }
    if include_comparators:
        zero = sim(Costs(0, 0, 0, 0, "simple_debit"))
        first = specs[0].eval_start
        last = specs[-1].eval_end
        lo = _long_only(ds, a, b, arr, first, last, p, costs)
        lo_dates = [ds.calendar[i].strftime("%Y-%m-%d") for i in range(first, last + 1)]
        stress = []
        for bps in p.stress_bps:
            c = Costs(bps / 4, bps / 2, bps / 4, p.borrow_annual, "price_slippage")
            r = sim(c)
            stress.append({"friction_bps_per_leg_per_fill": bps, "borrow_annual": p.borrow_annual,
                           "split": f"slippage {bps/2:g} bps in price + commission {bps/4:g} + levy {bps/4:g} bps",
                           "net_return": equity_metrics([d["equity"] for d in r["daily"]], p.starting_equity)["net_return"],
                           "trade_count": len(r["trades"]),
                           "total_cost": r["totals"]["fees"] + r["totals"]["slippage_cost"] + r["totals"]["borrow"]})
        out["comparators"] = {
            "cash": {"description": "No trading; cash earns the same 0% interest assumption",
                     "net_return": 0.0},
            "zero_friction": {"description": "Same signals and folds; no commission, slippage, levy or borrow",
                              "metrics": _segments(zero["daily"], p, holdout_date),
                              "equity": [d["equity"] for d in zero["daily"]], "trade_count": len(zero["trades"])},
            "long_only_ab": {"description": f"Buy {p.gross_exposure*50:.0f}% of equity in each of {a} and {b} at "
                                            "the first evaluation open, hold to the final close; same cost convention; "
                                            "a descriptive comparison, not a benchmark",
                             "dates": lo_dates, "equity": lo,
                             "metrics": equity_metrics(lo, p.starting_equity)},
        }
        out["stress"] = stress
    out["manifest"] = experiment_manifest(kind="pair_backtest", ds=ds, params=p,
                                          observation_cutoff=ds.calendar[-1].strftime("%Y-%m-%d"),
                                          extra={"pair": out["pair"], "strict": strict})
    out["result_sha256"] = stable_hash({k: out[k] for k in ("folds", "trades", "fills", "daily", "metrics")})
    return out
