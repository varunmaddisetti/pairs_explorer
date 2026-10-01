"""Gates J3/J5: directions, thresholds, exits, cooldown, fill timing, invalid-data states."""
import numpy as np
import pytest

from app.backtest.metrics import equity_metrics
from conftest import Toy


def entries(r):
    return [(t["side"], t["entry_date"]) for t in r["trades"]]


@pytest.mark.parametrize("z,side", [(-2.0, "long_spread"), (-3.49, "long_spread"), (2.0, "short_spread"),
                                    (3.49, "short_spread")])
def test_entry_band_directions(z, side):
    t = Toy(); t.z[0] = z; t.z[1:] = z
    r = t.run()
    assert r["trades"] or r["open_trade"] is None
    tr = r["trades"][0]
    assert tr["side"] == side
    q_sign = 1 if side == "long_spread" else -1
    assert np.sign(tr["q_a"]) == q_sign and np.sign(tr["q_b"]) == -q_sign


@pytest.mark.parametrize("z", [-3.5, 3.5, -1.99, 1.99, -4.0, 4.0])
def test_no_entry_outside_band(z):
    t = Toy(); t.z[:] = z
    assert t.run()["trades"] == []


def test_adverse_exit_long_and_short():
    for z_in, z_bad, reason in [(-2.5, -3.5, "adverse_z"), (2.5, 3.5, "adverse_z")]:
        t = Toy(); t.z[0] = z_in; t.z[1:3] = z_in; t.z[3] = z_bad; t.z[4:] = 0.0
        tr = t.run()["trades"][0]
        assert tr["exit_reason"] == reason
        assert tr["exit_signal_date"] == str(t.dates[3].date())
        assert tr["exit_date"] == str(t.dates[4].date())        # next open, never the signal close


def test_overshoot_across_mean_exits_on_convergence():
    t = Toy(); t.z[0] = -2.5; t.z[1] = -2.5; t.z[2] = 1.5; t.z[3:] = 1.5
    tr = t.run()["trades"][0]
    assert tr["exit_reason"] == "convergence"
    assert tr["exit_signal_date"] == str(t.dates[2].date())
    t2 = Toy(); t2.z[0] = 2.5; t2.z[1] = 2.5; t2.z[2] = -1.2; t2.z[3:] = -1.2
    assert t2.run()["trades"][0]["exit_reason"] == "convergence"


def test_short_spread_does_not_exit_while_above_band():
    t = Toy(); t.z[0] = 2.5; t.z[1:5] = 0.6; t.z[5:] = 0.5
    tr = t.run()["trades"][0]
    assert tr["exit_signal_date"] == str(t.dates[5].date())      # z <= 0.5 needed


def test_max_holding_period():
    t = Toy(n=60); t.z[:] = -2.4
    r = t.run()
    tr = r["trades"][0]
    assert tr["exit_reason"] == "max_holding"
    entry_i = 1
    assert tr["exit_signal_date"] == str(t.dates[entry_i + 19].date())   # 20th held close
    assert tr["exit_date"] == str(t.dates[entry_i + 20].date())


def test_exit_priority_adverse_beats_max_hold():
    t = Toy(n=60); t.z[:] = -2.4; t.z[20] = -3.6
    assert t.run()["trades"][0]["exit_reason"] == "adverse_z"


def test_cooldown_one_complete_session():
    t = Toy(n=60); t.z[:] = -2.4
    r = t.run()
    first, second = r["trades"][0], r["trades"][1]
    exit_i = list(t.dates.strftime("%Y-%m-%d")).index(first["exit_date"])
    entry_i = list(t.dates.strftime("%Y-%m-%d")).index(second["entry_date"])
    assert entry_i == exit_i + 2          # exit session, one full flat session, then re-entry open
    suppressed = [d for d in r["decisions"] if d.get("note", "").startswith("entry suppressed: re-entry cooldown")]
    assert suppressed and suppressed[0]["date"] == first["exit_date"]


def test_fill_timing_first_bar_and_next_open():
    t = Toy(); t.z[0] = -2.5; t.z[1:] = -2.5; t.oa[1] = 101.0
    r = t.run()
    tr = r["trades"][0]
    assert tr["signal_date"] == str(t.dates[0].date())   # last formation close
    assert tr["entry_date"] == str(t.dates[1].date())    # first evaluation open
    assert tr["entry_ref_a"] == 101.0                    # open price, not the signal close
    for d in r["decisions"]:
        if d.get("fill_date"):
            assert d["fill_date"] > d["date"]


def test_no_entry_on_final_session_and_boundary_exit():
    t = Toy(n=10); t.z[:] = 0.0; t.z[8] = -2.5        # signal at close 8 would fill on final session 9
    r = t.run()
    assert r["trades"] == []
    t2 = Toy(n=10); t2.z[:] = -2.4; t2.z[0] = -2.5
    r2 = t2.run()
    last = r2["trades"][-1]
    assert last["exit_reason"] == "fold_boundary" and last["exit_time"] == "close"
    assert last["exit_date"] == str(t2.dates[9].date())
    assert r2["daily"][-1]["position"] == "flat"


def test_missing_fill_cancels_entry():
    t = Toy(); t.z[0] = -2.5; t.z[1:] = 0.0; t.oa[1] = np.nan; t.ca[1] = np.nan
    r = t.run()
    assert r["trades"] == []
    assert any(e["type"] == "entry_cancelled" for e in r["events"])


def test_missing_valuation_while_holding_halts():
    t = Toy(); t.z[0] = -2.5; t.z[1:] = -2.4; t.ca[4] = np.nan
    r = t.run()
    assert r["status"]["halted"] and "unresolved exposure" in r["status"]["halt_reason"]
    assert r["status"]["unresolved_exposure"]["q_a"] != 0
    assert r["open_trade"] is not None


def test_insolvency_halts_and_reports():
    t = Toy(); t.z[0] = 2.5; t.z[1:] = 2.4            # short spread: short A
    t.ca[2:] = 500.0; t.oa[2:] = 500.0                  # A quintuples
    r = t.run()
    assert r["status"]["insolvent"] and r["status"]["halted"]
    assert r["open_trade"] is not None
    m = equity_metrics([d["equity"] for d in r["daily"]], 100000)
    assert m["annualized_return"] is None


def test_metrics_never_nan():
    m = equity_metrics([100000.0] * 300, 100000)
    assert m["sharpe"] is None and m["annualized_volatility"] == 0.0
    assert equity_metrics([], 100000)["net_return"] is None
