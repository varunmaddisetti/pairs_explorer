"""Gates J1/J2: accounting and cost oracles, slippage convention, ledger reconciliation."""
import numpy as np
import pytest

from app.backtest.engine import Costs
from app.backtest.run import run_pair_backtest
from conftest import ZERO, Toy


def _oracle_market(side_z):
    t = Toy()
    t.z[0] = side_z            # signal at the last formation close
    t.z[1] = side_z
    t.z[2] = 0.0               # convergence observed at close of session 2 -> exit at open 3
    t.oa[3:] = 110.0; t.ca[3:] = 110.0
    t.ob[3:] = 190.0; t.cb[3:] = 190.0
    return t


@pytest.mark.parametrize("side_z,expected", [(-2.5, 6750.0), (2.5, -6750.0)])
def test_zero_friction_oracle(side_z, expected):
    r = _oracle_market(side_z).run()
    (tr,) = r["trades"]
    sign = 1 if side_z < 0 else -1
    assert tr["q_a"] == pytest.approx(sign * 450.0)
    assert tr["q_b"] == pytest.approx(-sign * 225.0)
    assert tr["gross_entry"] == pytest.approx(90000.0)
    assert tr["gross_pnl"] == pytest.approx(expected)
    assert tr["net_pnl"] == pytest.approx(expected)
    assert tr["exit_reason"] == "convergence"
    final = r["daily"][-1]
    assert final["equity"] == pytest.approx(100000 + expected)
    assert final["cash"] == pytest.approx(100000 + expected)        # flat: equity is all cash
    assert final["q_a"] == 0 and final["q_b"] == 0


def test_cost_oracle_simple_debit():
    costs = Costs(commission_bps=20, slippage_bps=0, levy_bps=0, borrow_annual=0, mode="simple_debit")
    r = _oracle_market(-2.5).run(costs=costs)
    (tr,) = r["trades"]
    assert tr["exit_notional"] == pytest.approx(92250.0)
    assert tr["fees"] == pytest.approx((90000 + 92250) * 0.002)       # 364.50
    assert tr["fees"] == pytest.approx(364.50)
    assert tr["net_pnl"] == pytest.approx(6385.50)
    assert r["daily"][-1]["equity"] == pytest.approx(106385.50)


def test_simple_debit_mode_does_not_also_move_prices():
    costs = Costs(5, 10, 5, 0, "simple_debit")
    r = _oracle_market(-2.5).run(costs=costs)
    for f in r["fills"]:
        assert f["exec_price"] == f["ref_price"]
        assert f["slippage_cost"] == 0
        assert f["fee"] == pytest.approx(f["notional"] * 0.002)


def test_production_slippage_is_in_price_and_not_double_counted():
    costs = Costs(commission_bps=0, slippage_bps=10, levy_bps=0, borrow_annual=0, mode="price_slippage")
    r = _oracle_market(-2.5).run(costs=costs)
    (tr,) = r["trades"]
    buy_a, sell_b = 100 * 1.001, 200 * 0.999
    qa, qb = 45000 / buy_a, -45000 / sell_b
    assert tr["q_a"] == pytest.approx(qa) and tr["q_b"] == pytest.approx(qb)
    exit_cash = qa * 110 * 0.999 + qb * 190 * 1.001
    expected_net = -(qa * buy_a + qb * sell_b) + exit_cash
    assert tr["net_pnl"] == pytest.approx(expected_net)
    assert tr["fees"] == 0.0                                      # slippage is never also a fee
    assert tr["net_pnl"] == pytest.approx(tr["gross_pnl"] - tr["slippage_cost"])
    assert tr["slippage_cost"] == pytest.approx(sum(abs(f["qty"]) * abs(f["exec_price"] - f["ref_price"])
                                                    for f in r["fills"]))


def test_fees_and_slippage_together_reconcile():
    costs = Costs(5, 10, 5, 0, "price_slippage")
    r = _oracle_market(2.5).run(costs=costs)
    (tr,) = r["trades"]
    assert tr["net_pnl"] == pytest.approx(tr["gross_pnl"] - tr["fees"] - tr["slippage_cost"] - tr["borrow_cost"])
    assert tr["fees"] == pytest.approx(sum(f["notional"] for f in r["fills"]) * 0.001)


def test_borrow_act365_on_short_leg():
    t = Toy()
    t.z[0] = -2.5                   # long spread: short B (225 sh x 200 = 45,000)
    t.z[1:6] = -2.4
    t.z[5] = 0.0                    # exit decided at close 5 (Mon 2024-01-08) -> fill open 6 (Tue 01-09)
    r = t.run(costs=Costs(0, 0, 0, 0.05, "simple_debit"))
    (tr,) = r["trades"]
    assert tr["entry_date"] == "2024-01-02" and tr["exit_date"] == "2024-01-09"
    days = 7                         # calendar days entry date -> exit date, intraday intervals count 0
    assert tr["borrow_cost"] == pytest.approx(0.05 * 45000 * days / 365)


def test_short_proceeds_do_not_raise_exposure():
    t = Toy()
    t.z[0] = 2.5
    t.z[1:] = 2.4
    r = t.run()
    day = r["daily"][0]
    assert day["gross_exposure"] == pytest.approx(90000)
    assert day["cash"] == pytest.approx(100000)      # +45k short proceeds -45k long purchase


def test_real_run_ledger_reconciles(ds, params):
    r = run_pair_backtest(ds, "S_BANK_A", "S_BANK_B", params)
    arr = ds.panel("S_BANK_A", "S_BANK_B").reindex(ds.calendar)
    ca = dict(zip(ds.calendar.strftime("%Y-%m-%d"), arr["close_a"]))
    cb = dict(zip(ds.calendar.strftime("%Y-%m-%d"), arr["close_b"]))
    for d in r["daily"]:
        assert d["equity"] == pytest.approx(d["cash"] + d["q_a"] * ca[d["date"]] + d["q_b"] * cb[d["date"]], abs=1e-6)
    for f in r["fills"]:
        assert np.isfinite(f["equity_after"])
    total_net = sum(t["net_pnl"] for t in r["trades"])
    assert r["daily"][-1]["equity"] == pytest.approx(params.starting_equity + total_net, abs=1e-6)
    tot = r["totals"]
    gross = sum(t["gross_pnl"] for t in r["trades"])
    assert total_net == pytest.approx(gross - tot["fees"] - tot["slippage_cost"] - tot["borrow"], abs=1e-6)
    for tr in r["trades"]:
        assert tr["pre_entry_equity"] * params.gross_exposure == pytest.approx(tr["gross_entry"])
