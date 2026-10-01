"""Gates J4/J6: future-data perturbation and fold/holdout separation."""
import numpy as np
import pandas as pd
import pytest

from app.analytics.family import evaluate_family, holdout_start_index, scanner
from app.analytics.pair_detail import pair_detail
from app.analytics.stats import engle_granger, fdr_by
from app.backtest.run import run_pair_backtest
from app.providers.base import Dataset

PAIRS = [("S_BANK_A", "S_BANK_B"), ("S_BREAK_A", "S_BREAK_B")]


def perturbed_after(ds: Dataset, cutoff: pd.Timestamp, seed=7) -> Dataset:
    """Scale every OHLC observation strictly after `cutoff` by a random factor per row.
    Dates, symbols and dataset identity (id + content hash) are preserved on purpose."""
    f = ds.frame.copy()
    rng = np.random.default_rng(seed)
    m = f["date"] > cutoff
    k = np.exp(rng.normal(0, 0.05, m.sum()))
    for c in ("open", "high", "low", "close"):
        f.loc[m, c] = f.loc[m, c].to_numpy() * k
    return Dataset(f, ds.mode, ds.manifest, ds.report, ds.groups, ds.universe_version, ds.calendar,
                   ds.content_hash, ds.corporate_actions_accounted)


def _upto(rows, key, t):
    return [r for r in rows if r[key] <= t]


@pytest.mark.parametrize("cut_idx", [600, 800, 1010])
def test_future_perturbation_does_not_change_past(ds, params, cut_idx):
    t = ds.calendar[cut_idx]
    ts = t.strftime("%Y-%m-%d")
    alt = perturbed_after(ds, t)
    assert alt.frame.loc[alt.frame["date"] > t, "close"].ne(ds.frame.loc[ds.frame["date"] > t, "close"]).all()
    assert scanner(ds, t, params) == scanner(alt, t, params)
    for a, b in PAIRS:
        d0, d1 = pair_detail(ds, a, b, t, params), pair_detail(alt, a, b, t, params)
        for k in ("stats", "family", "formation", "descriptive", "beta_history", "walk_forward", "explanation"):
            assert d0[k] == d1[k], k
        r0, r1 = run_pair_backtest(ds, a, b, params), run_pair_backtest(alt, a, b, params)
        assert _upto(r0["decisions"], "date", ts) == _upto(r1["decisions"], "date", ts)
        assert _upto(r0["fills"], "date", ts) == _upto(r1["fills"], "date", ts)
        assert _upto(r0["daily"], "date", ts) == _upto(r1["daily"], "date", ts)
        assert _upto(r0["folds"], "formation_end", ts) == _upto(r1["folds"], "formation_end", ts)
        e0 = [{k: v for k, v in x.items() if k.startswith(("entry", "signal", "q_", "beta", "side", "pre_"))}
              for x in r0["trades"] if x["entry_date"] <= ts]
        e1 = [{k: v for k, v in x.items() if k.startswith(("entry", "signal", "q_", "beta", "side", "pre_"))}
              for x in r1["trades"] if x["entry_date"] <= ts]
        assert e0 == e1


def test_holdout_outcomes_do_not_affect_development(ds, params):
    hs = holdout_start_index(len(ds.calendar), params)
    assert hs == len(ds.calendar) - 252
    last_dev_close = ds.calendar[hs - 1]
    alt = perturbed_after(ds, last_dev_close, seed=11)
    for a, b in PAIRS:
        r0, r1 = run_pair_backtest(ds, a, b, params), run_pair_backtest(alt, a, b, params)
        dev0 = [f for f in r0["folds"] if f["segment"] == "development"]
        dev1 = [f for f in r1["folds"] if f["segment"] == "development"]
        assert dev0 == dev1 and len(dev0) == 12
        assert r0["metrics"]["segments"]["development"] == r1["metrics"]["segments"]["development"]
        assert r0["manifest"]["params"] == r1["manifest"]["params"]
    assert alt.frame.loc[alt.frame["date"] >= ds.calendar[hs], "close"].ne(
        ds.frame.loc[ds.frame["date"] >= ds.calendar[hs], "close"]).all()


def test_fdr_family_uses_only_formation_data(ds, params):
    end = ds.calendar[251 + 7 * 63]
    fam = evaluate_family(ds, end, params)
    pv = []
    for r in fam["pairs"]:
        p = ds.panel(r["a"], r["b"]).loc[:end].iloc[-252:]
        assert p.index[-1] == end and len(p) == 252
        eg = engle_granger(np.log(p["close_a"].to_numpy()), np.log(p["close_b"].to_numpy()))
        assert eg["pvalue"] == pytest.approx(r["coint_p"], rel=1e-12)
        pv.append(eg["pvalue"])
    _, adj = fdr_by(pv, 0.05)
    assert [r["coint_p_adj"] for r in fam["pairs"]] == pytest.approx(adj)
    assert fam["family"]["family_size"] == 4
