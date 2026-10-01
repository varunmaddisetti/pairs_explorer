"""Chronological, event-driven pair-sleeve backtest with an explicit cash/position ledger.

Timing (build kit section G1):
* decisions are made from the close of session t and execute at the open of t+1;
* the first decision uses the last formation close and may fill at the first evaluation open;
* open positions are flattened at the final evaluation-block close (scheduled boundary exit);
* parameters are frozen per fold; no refit mid-trade.

Exit priority at a close: data/model-invalid -> adverse threshold -> maximum holding -> convergence;
the scheduled fold boundary is applied at the final close of the block.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..config import ResearchParams

LONG, SHORT, FLAT = 1, -1, 0


@dataclass
class FoldSpec:
    k: int
    form_end: int          # index of the last formation close (first decision time)
    eval_start: int
    eval_end: int          # scheduled boundary-exit close
    segment: str
    tradable: bool
    beta: float | None
    z: np.ndarray          # z-score per calendar index under this fold's frozen parameters (NaN elsewhere)
    exclusion: list[str] = field(default_factory=list)


@dataclass
class Costs:
    commission_bps: float
    slippage_bps: float
    levy_bps: float
    borrow_annual: float
    mode: str  # "price_slippage" | "simple_debit"

    @classmethod
    def from_params(cls, p: ResearchParams) -> "Costs":
        return cls(p.commission_bps, p.slippage_bps, p.levy_bps, p.borrow_annual, p.friction_mode)

    @property
    def fee_rate(self) -> float:
        """Rate debited explicitly as a fee on traded notional."""
        if self.mode == "simple_debit":
            return (self.commission_bps + self.slippage_bps + self.levy_bps) / 1e4
        return (self.commission_bps + self.levy_bps) / 1e4

    @property
    def slip_rate(self) -> float:
        """Adverse execution-price adjustment (zero in simple_debit mode: no double counting)."""
        return self.slippage_bps / 1e4 if self.mode == "price_slippage" else 0.0


class Ledger:
    """Cash/position ledger. Short-sale proceeds sit in cash and never raise gross exposure."""

    def __init__(self, equity: float, sym_a: str, sym_b: str):
        self.cash = float(equity)
        self.q = {"A": 0.0, "B": 0.0}
        self.sym = {"A": sym_a, "B": sym_b}
        self.last_px: dict[str, float] = {"A": float("nan"), "B": float("nan")}
        self.last_val_date: pd.Timestamp | None = None
        self.fills: list[dict] = []
        self.fees = 0.0
        self.slippage = 0.0
        self.borrow = 0.0
        self.traded_notional = 0.0

    def equity(self, px_a: float, px_b: float) -> float:
        return self.cash + self.q["A"] * px_a + self.q["B"] * px_b

    def short_mv(self) -> float:
        return sum(-q * self.last_px[k] for k, q in self.q.items() if q < 0)

    def accrue_borrow(self, date: pd.Timestamp, rate: float) -> float:
        """ACT/365 on the previous available short market value for calendar days elapsed."""
        if self.last_val_date is None:
            self.last_val_date = date
            return 0.0
        days = (date - self.last_val_date).days
        amt = 0.0
        if days > 0 and rate > 0:
            smv = self.short_mv()
            if smv > 0:
                amt = rate * smv * days / 365.0
                self.cash -= amt
                self.borrow += amt
        self.last_val_date = date
        return amt

    def trade(self, leg: str, qty: float, ref: float, costs: Costs, date: pd.Timestamp, when: str,
              reason: str) -> dict:
        side = 1.0 if qty > 0 else -1.0
        px = ref * (1 + side * costs.slip_rate)            # adverse to the trader
        notional = abs(qty) * px
        fee = notional * costs.fee_rate
        slip = abs(qty) * abs(px - ref)
        self.cash -= qty * px + fee
        self.q[leg] += qty
        if abs(self.q[leg]) < 1e-9:
            self.q[leg] = 0.0
        self.fees += fee
        self.slippage += slip
        self.traded_notional += notional
        self.last_px[leg] = ref
        row = {"date": date.strftime("%Y-%m-%d"), "time": when, "leg": leg, "symbol": self.sym[leg],
               "qty": qty, "ref_price": ref, "exec_price": px, "notional": notional, "fee": fee,
               "slippage_cost": slip, "reason": reason}
        self.fills.append(row)
        return row


def _side_name(side: int) -> str:
    return "long_spread" if side == LONG else "short_spread"


def simulate_sleeve(dates: pd.DatetimeIndex, open_a: np.ndarray, close_a: np.ndarray, open_b: np.ndarray,
                    close_b: np.ndarray, folds: list[FoldSpec], p: ResearchParams, costs: Costs,
                    sym_a: str = "A", sym_b: str = "B") -> dict[str, Any]:
    led = Ledger(p.starting_equity, sym_a, sym_b)
    side = FLAT
    entry_idx = -1
    last_exit_idx = -10 ** 9
    trade: dict | None = None
    trades: list[dict] = []
    decisions: list[dict] = []
    events: list[dict] = []
    daily: list[dict] = []
    status = {"insolvent": False, "halted": False, "halt_reason": None, "unresolved_exposure": None}

    def fill_entry(i: int, new_side: int, beta: float, k: int, sig_i: int, z_sig: float) -> bool:
        nonlocal side, entry_idx, trade
        oa, ob = open_a[i], open_b[i]
        if not (np.isfinite(oa) and np.isfinite(ob)):
            events.append({"date": dates[i].strftime("%Y-%m-%d"), "type": "entry_cancelled",
                           "reason": "missing open price for a leg at the scheduled fill", "fold": k})
            return False
        led.accrue_borrow(dates[i], costs.borrow_annual)
        e_pre = led.equity(oa, ob)  # flat: equals cash
        if e_pre <= 0:
            events.append({"date": dates[i].strftime("%Y-%m-%d"), "type": "entry_cancelled",
                           "reason": "nonpositive pre-entry equity", "fold": k})
            return False
        g = p.gross_exposure * e_pre
        w_a, w_b = 1.0 / (1.0 + beta), beta / (1.0 + beta)
        slip = costs.slip_rate
        # quantities sized on execution prices so traded gross notional equals G exactly
        px_a = oa * (1 + new_side * slip)
        px_b = ob * (1 - new_side * slip)
        q_a = new_side * g * w_a / px_a
        q_b = -new_side * g * w_b / px_b
        cash0, fees0, slip0 = led.cash, led.fees, led.slippage
        led.trade("A", q_a, oa, costs, dates[i], "open", "entry")
        led.trade("B", q_b, ob, costs, dates[i], "open", "entry")
        eq = led.equity(oa, ob)
        for f in led.fills[-2:]:
            f["equity_after"] = eq
            f["cash_after"] = led.cash
        side, entry_idx = new_side, i
        trade = {"fold": k, "side": _side_name(new_side), "signal_date": dates[sig_i].strftime("%Y-%m-%d"),
                 "signal_z": z_sig, "entry_date": dates[i].strftime("%Y-%m-%d"), "entry_index": i,
                 "beta": beta, "q_a": q_a, "q_b": q_b, "entry_ref_a": oa, "entry_ref_b": ob,
                 "entry_exec_a": px_a, "entry_exec_b": px_b, "pre_entry_equity": e_pre, "gross_entry": g,
                 "entry_net_exposure": q_a * oa + q_b * ob,
                 "_cash0": cash0 + 0.0, "_fees0": fees0, "_slip0": slip0, "_borrow0": led.borrow}
        return True

    def fill_exit(i: int, when: str, reason: str, sig_i: int | None, z_sig: float | None) -> bool:
        nonlocal side, trade, last_exit_idx
        pa = open_a[i] if when == "open" else close_a[i]
        pb = open_b[i] if when == "open" else close_b[i]
        if not (np.isfinite(pa) and np.isfinite(pb)):
            status.update(halted=True, halt_reason=f"missing {when} price on {dates[i]:%Y-%m-%d} while holding; "
                          "exit cannot be valued - unresolved exposure",
                          unresolved_exposure={"q_a": led.q["A"], "q_b": led.q["B"],
                                               "last_known_price_a": led.last_px["A"],
                                               "last_known_price_b": led.last_px["B"]})
            return False
        led.accrue_borrow(dates[i], costs.borrow_annual)
        qa, qb = led.q["A"], led.q["B"]
        led.trade("A", -qa, pa, costs, dates[i], when, reason)
        led.trade("B", -qb, pb, costs, dates[i], when, reason)
        eq = led.equity(pa, pb)
        for f in led.fills[-2:]:
            f["equity_after"] = eq
            f["cash_after"] = led.cash
        assert trade is not None
        gross = trade["q_a"] * (pa - trade["entry_ref_a"]) + trade["q_b"] * (pb - trade["entry_ref_b"])
        fees = led.fees - trade.pop("_fees0")
        slip = led.slippage - trade.pop("_slip0")
        borrow = led.borrow - trade.pop("_borrow0")
        cash0 = trade.pop("_cash0")
        trade.update(exit_date=dates[i].strftime("%Y-%m-%d"), exit_time=when, exit_reason=reason,
                     exit_signal_date=dates[sig_i].strftime("%Y-%m-%d") if sig_i is not None else None,
                     exit_signal_z=z_sig, exit_ref_a=pa, exit_ref_b=pb,
                     exit_notional=abs(trade["q_a"]) * pa + abs(trade["q_b"]) * pb,
                     holding_sessions=i - trade["entry_index"] + 1, gross_pnl=gross, fees=fees,
                     slippage_cost=slip, borrow_cost=borrow, net_pnl=led.cash - cash0)
        trades.append(trade)
        trade = None
        side = FLAT
        last_exit_idx = i
        return True

    def mark(i: int, fold_k: int | None, segment: str) -> None:
        ca, cb = close_a[i], close_b[i]
        holding = side != FLAT
        if holding and not (np.isfinite(ca) and np.isfinite(cb)):
            status.update(halted=True, halt_reason=f"missing close on {dates[i]:%Y-%m-%d} while holding; "
                          "position cannot be valued - unresolved exposure",
                          unresolved_exposure={"q_a": led.q["A"], "q_b": led.q["B"]})
            return
        led.accrue_borrow(dates[i], costs.borrow_annual if holding else 0.0)
        if holding:
            led.last_px = {"A": float(ca), "B": float(cb)}
        eq = led.equity(ca if holding else 0.0, cb if holding else 0.0)
        long_mv = sum(q * (ca if k == "A" else cb) for k, q in led.q.items() if q > 0)
        short_mv = sum(-q * (ca if k == "A" else cb) for k, q in led.q.items() if q < 0)
        daily.append({"date": dates[i].strftime("%Y-%m-%d"), "index": i, "fold": fold_k, "segment": segment,
                      "position": _side_name(side) if holding else "flat", "q_a": led.q["A"], "q_b": led.q["B"],
                      "cash": led.cash, "long_mv": long_mv, "short_mv": short_mv,
                      "gross_exposure": long_mv + short_mv, "net_exposure": long_mv - short_mv,
                      "equity": eq, "cum_fees": led.fees, "cum_borrow": led.borrow,
                      "cum_slippage": led.slippage})
        if eq <= 0:
            status.update(insolvent=True, halted=True, halt_reason=f"equity nonpositive on {dates[i]:%Y-%m-%d}",
                          unresolved_exposure={"q_a": led.q["A"], "q_b": led.q["B"], "equity": eq})

    def decide(i: int, f: FoldSpec) -> tuple | None:
        """Signal at close i -> order for open i+1. Returns (kind, side_or_reason, z)."""
        z = f.z[i]
        rec = {"date": dates[i].strftime("%Y-%m-%d"), "fold": f.k, "z": None if not np.isfinite(z) else float(z),
               "position": _side_name(side) if side != FLAT else "flat", "action": "none"}
        order = None
        if side != FLAT:
            held = i - entry_idx + 1
            if not np.isfinite(z):
                order = ("exit", "data_or_model_invalid", z)
            elif (side == LONG and z <= -p.adverse_z) or (side == SHORT and z >= p.adverse_z):
                order = ("exit", "adverse_z", z)
            elif held >= p.max_holding:
                order = ("exit", "max_holding", z)
            elif (side == LONG and z >= -p.exit_z) or (side == SHORT and z <= p.exit_z):
                order = ("exit", "convergence", z)
        elif f.tradable and np.isfinite(z) and not status["halted"]:
            nxt = i + 1
            want = LONG if -p.entry_z_max < z <= -p.entry_z else SHORT if p.entry_z <= z < p.entry_z_max else FLAT
            if want != FLAT:
                if nxt >= f.eval_end:
                    rec["note"] = "entry suppressed: fill would fall on the final session of the fold"
                elif nxt < last_exit_idx + p.cooldown_sessions + 1:
                    rec["note"] = "entry suppressed: re-entry cooldown"
                else:
                    order = ("entry", want, z)
        if order:
            rec["action"] = f"{order[0]}:{order[1] if order[0] == 'exit' else _side_name(order[1])}"
            rec["fill_date"] = dates[i + 1].strftime("%Y-%m-%d") if i + 1 < len(dates) else None
        if order or side != FLAT or (np.isfinite(z) and abs(z) >= p.entry_z):
            decisions.append(rec)
        return order

    for f in folds:
        if status["halted"]:
            break
        if not f.tradable:
            events.append({"date": dates[f.eval_start].strftime("%Y-%m-%d"), "type": "fold_not_traded",
                           "fold": f.k, "reason": "; ".join(f.exclusion) or "not eligible"})
        pending = decide(f.form_end, f) if f.tradable else None
        pending_sig = f.form_end
        for i in range(f.eval_start, f.eval_end + 1):
            if pending is not None:
                kind, what, zsig = pending
                if kind == "entry":
                    fill_entry(i, what, float(f.beta), f.k, pending_sig, float(zsig))
                else:
                    fill_exit(i, "open", what, pending_sig, None if not np.isfinite(zsig) else float(zsig))
                pending = None
                if status["halted"]:
                    break
            mark(i, f.k, f.segment)
            if status["halted"]:
                break
            if i == f.eval_end:
                if side != FLAT:
                    fill_exit(i, "close", "fold_boundary", None, None)
                    daily[-1].update(cash=led.cash, q_a=0.0, q_b=0.0, long_mv=0.0, short_mv=0.0,
                                     gross_exposure=0.0, net_exposure=0.0, equity=led.cash,
                                     cum_fees=led.fees, cum_borrow=led.borrow, cum_slippage=led.slippage,
                                     position="flat")
                break
            pending = decide(i, f)
            pending_sig = i

    if trade is not None:
        trade["open_at_end"] = True
        for key in ("_cash0", "_fees0", "_slip0", "_borrow0"):
            trade.pop(key, None)
    return {"trades": trades, "fills": led.fills, "daily": daily, "decisions": decisions, "events": events,
            "status": status, "open_trade": trade,
            "totals": {"fees": led.fees, "slippage_cost": led.slippage, "borrow": led.borrow,
                       "traded_notional": led.traded_notional, "final_cash": led.cash,
                       "final_q_a": led.q["A"], "final_q_b": led.q["B"]}}


def finite(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x
