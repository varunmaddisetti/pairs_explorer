"""Performance metrics. Every metric is either a finite number or None (never NaN/inf).

Definitions (daily equity E_t over the evaluated sessions, r_t = E_t / E_{t-1} - 1):
* net_return            = E_end / E_start - 1
* annualized_return     = (E_end / E_start)^(252/n) - 1, only if n >= 252 sessions and E_end > 0
* annualized_volatility = sd(r_t, ddof=1) * sqrt(252), needs n >= 2 returns
* sharpe                = mean(r_t - rf_daily) / sd(r_t - rf_daily, ddof=1) * sqrt(252); rf=0 default;
                          None when the denominator is zero or fewer than 20 returns
* max_drawdown          = min_t (E_t / max_{s<=t} E_s - 1)
* turnover              = total traded notional / mean equity
* win_rate              = winning trades / trades, only with >= 5 closed trades
* profit_factor         = sum(winning net P&L) / |sum(losing net P&L)|, needs >= 5 trades and a loss
"""
from __future__ import annotations

import math

import numpy as np

MIN_TRADES_FOR_RATIOS = 5
MIN_RETURNS_FOR_SHARPE = 20
ANNUALIZATION = 252


def _f(x: float | None) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def equity_metrics(equity: list[float], start_equity: float, risk_free_annual: float = 0.0) -> dict:
    e = np.asarray([start_equity] + list(equity), dtype=float)
    n = len(e) - 1
    out: dict = {"sessions": n, "start_equity": start_equity, "end_equity": _f(e[-1]) if n else start_equity}
    if n == 0:
        return out | {"net_return": None, "annualized_return": None, "annualized_volatility": None,
                      "sharpe": None, "max_drawdown": None}
    out["net_return"] = _f(e[-1] / e[0] - 1)
    out["annualized_return"] = (_f((e[-1] / e[0]) ** (ANNUALIZATION / n) - 1)
                                if n >= ANNUALIZATION and e[-1] > 0 and e[0] > 0 else None)
    r = e[1:] / e[:-1] - 1 if (e[:-1] > 0).all() else None
    if r is not None and len(r) >= 2:
        sd = float(np.std(r, ddof=1))
        out["annualized_volatility"] = _f(sd * math.sqrt(ANNUALIZATION))
        ex = r - risk_free_annual / ANNUALIZATION
        sdx = float(np.std(ex, ddof=1))
        out["sharpe"] = (_f(float(np.mean(ex)) / sdx * math.sqrt(ANNUALIZATION))
                         if sdx > 1e-15 and len(r) >= MIN_RETURNS_FOR_SHARPE else None)
    else:
        out["annualized_volatility"] = None
        out["sharpe"] = None
    peak = np.maximum.accumulate(e)
    out["max_drawdown"] = _f(float(np.min(e / peak - 1))) if (peak > 0).all() else None
    return out


def trade_metrics(trades: list[dict], traded_notional: float, mean_equity: float | None) -> dict:
    closed = [t for t in trades if "net_pnl" in t]
    n = len(closed)
    pnl = np.array([t["net_pnl"] for t in closed], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    out = {
        "trade_count": n,
        "avg_holding_sessions": _f(float(np.mean([t["holding_sessions"] for t in closed]))) if n else None,
        "max_holding_sessions": int(max(t["holding_sessions"] for t in closed)) if n else None,
        "exit_reasons": {r: sum(t["exit_reason"] == r for t in closed)
                         for r in sorted({t["exit_reason"] for t in closed})},
        "turnover": _f(traded_notional / mean_equity) if mean_equity and mean_equity > 0 else None,
        "win_rate": _f(len(wins) / n) if n >= MIN_TRADES_FOR_RATIOS else None,
        "profit_factor": (_f(float(wins.sum()) / abs(float(losses.sum())))
                          if n >= MIN_TRADES_FOR_RATIOS and len(losses) else None),
        "gross_pnl": _f(float(sum(t["gross_pnl"] for t in closed))),
        "net_pnl": _f(float(pnl.sum())) if n else 0.0,
    }
    if n < MIN_TRADES_FOR_RATIOS:
        out["ratio_note"] = f"win rate / profit factor unavailable with fewer than {MIN_TRADES_FOR_RATIOS} trades"
    return out
