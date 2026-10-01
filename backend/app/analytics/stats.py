"""Deterministic statistical primitives (build kit section F).

Orientation: A is the lexicographically first symbol, B the second; never chosen by p-value.
    log(P_A,t) = alpha + beta * log(P_B,t) + residual_t
    s_t = log(P_A,t) - alpha - beta * log(P_B,t)
    mu, sigma = mean, sample sd (ddof=1) of the last `calibration_window` formation residuals
    z_t = (s_t - mu) / sigma
"""
from __future__ import annotations

import math
import warnings
from dataclasses import asdict, dataclass, field

import numpy as np
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.stattools import adfuller, coint, kpss

SIGMA_FLOOR = 1e-8          # spread sd below this is treated as degenerate
COLLINEAR_R2 = 1 - 1e-10    # log-level R^2 above this = (almost) identical series
CONSTANT_SD = 1e-12


def schwert_maxlag(nobs: int) -> int:
    """Explicit Schwert (1989) maximum lag 12*(n/100)^(1/4), as used by statsmodels' default."""
    return int(math.ceil(12.0 * (nobs / 100.0) ** 0.25))


@dataclass
class SpreadModel:
    valid: bool
    reasons: list[str] = field(default_factory=list)
    n_obs: int = 0
    alpha: float | None = None
    beta: float | None = None
    r2: float | None = None
    mu: float | None = None
    sigma: float | None = None

    def spread(self, log_a: np.ndarray, log_b: np.ndarray) -> np.ndarray:
        return np.asarray(log_a) - self.alpha - self.beta * np.asarray(log_b)

    def z(self, log_a: np.ndarray, log_b: np.ndarray) -> np.ndarray:
        return (self.spread(log_a, log_b) - self.mu) / self.sigma

    def to_dict(self) -> dict:
        return asdict(self)


def ols_alpha_beta(y: np.ndarray, x: np.ndarray) -> tuple[float, float, np.ndarray, int, float]:
    """OLS of y on [1, x] via least squares. Returns alpha, beta, residuals, rank, R^2."""
    X = np.column_stack([np.ones_like(x), x])
    coef, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / sst if sst > 0 else float("nan")
    return float(coef[0]), float(coef[1]), resid, int(rank), r2


def screen_pair(log_a: np.ndarray, log_b: np.ndarray, min_obs: int) -> list[str]:
    """Data/model validity reasons that make a pair an invalid independent pair."""
    reasons: list[str] = []
    if len(log_a) != len(log_b):
        return ["length_mismatch"]
    if len(log_a) < min_obs:
        reasons.append(f"insufficient_observations({len(log_a)}<{min_obs})")
        return reasons
    if not (np.isfinite(log_a).all() and np.isfinite(log_b).all()):
        return ["non_finite_values"]
    if np.std(log_a) < CONSTANT_SD or np.std(log_b) < CONSTANT_SD:
        return ["constant_series"]
    if np.array_equal(log_a, log_b):
        return ["duplicate_series"]
    return reasons


def fit_spread(log_a: np.ndarray, log_b: np.ndarray, calibration_window: int, min_obs: int) -> SpreadModel:
    log_a = np.asarray(log_a, dtype=float)
    log_b = np.asarray(log_b, dtype=float)
    reasons = screen_pair(log_a, log_b, min_obs)
    if reasons:
        return SpreadModel(False, reasons, len(log_a))
    alpha, beta, resid, rank, r2 = ols_alpha_beta(log_a, log_b)
    if rank < 2:
        return SpreadModel(False, ["rank_deficient_regression"], len(log_a))
    if not (math.isfinite(alpha) and math.isfinite(beta)):
        return SpreadModel(False, ["non_finite_coefficients"], len(log_a))
    if math.isfinite(r2) and r2 > COLLINEAR_R2:
        return SpreadModel(False, ["near_identical_series(log-level R2>1-1e-10)"], len(log_a), alpha, beta, r2)
    calib = resid[-calibration_window:]
    mu = float(np.mean(calib))
    sigma = float(np.std(calib, ddof=1))
    if not math.isfinite(sigma) or sigma < SIGMA_FLOOR:
        return SpreadModel(False, ["degenerate_spread_sigma"], len(log_a), alpha, beta, r2, mu, sigma)
    return SpreadModel(True, [], len(log_a), alpha, beta, r2, mu, sigma)


def engle_granger(log_a: np.ndarray, log_b: np.ndarray) -> dict:
    """Engle-Granger two-step test (null: NO cointegration) via statsmodels.tsa.stattools.coint.

    Settings (explicit): trend='c', method='aeg', maxlag=Schwert(n), autolag='aic'.
    """
    n = len(log_a)
    maxlag = min(schwert_maxlag(n), n // 2 - 2)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        stat, pval, crit = coint(log_a, log_b, trend="c", method="aeg", maxlag=maxlag, autolag="aic")
    collinear = any("colinear" in str(w.message) for w in caught)
    out = {
        "test": "Engle-Granger (statsmodels coint, trend='c', method='aeg', autolag='aic')",
        "null": "no cointegration",
        "statistic": float(stat) if math.isfinite(stat) else None,
        "pvalue": float(pval) if math.isfinite(pval) else None,
        "crit_1pct": float(crit[0]), "crit_5pct": float(crit[1]), "crit_10pct": float(crit[2]),
        "nobs": int(n), "maxlag": int(maxlag),
        "valid": (not collinear) and math.isfinite(stat) and math.isfinite(pval),
    }
    if collinear:
        out["invalid_reason"] = "collinear_series"
    return out


def half_life(resid: np.ndarray, min_obs: int = 30) -> dict:
    """Delta s_t = c + kappa * s_{t-1} + e_t ; rho = 1 + kappa ; half-life = -ln2/ln(rho) if 0<rho<1."""
    s = np.asarray(resid, dtype=float)
    if len(s) < min_obs or not np.isfinite(s).all():
        return {"status": "insufficient_data", "half_life": None, "rho": None, "kappa": None, "n_obs": int(len(s))}
    ds = np.diff(s)
    lag = s[:-1]
    if np.std(lag) < CONSTANT_SD:
        return {"status": "degenerate", "half_life": None, "rho": None, "kappa": None, "n_obs": int(len(s))}
    c, kappa, _, rank, _ = ols_alpha_beta(ds, lag)
    rho = 1.0 + kappa
    out = {"kappa": kappa, "rho": rho, "n_obs": int(len(s)), "half_life": None}
    if rank < 2 or not math.isfinite(rho):
        out["status"] = "degenerate"
    elif rho >= 1.0:
        out["status"] = "non_reverting(rho>=1)"
    elif rho <= 0.0:
        out["status"] = "oscillating(rho<=0)"
    else:
        hl = -math.log(2.0) / math.log(rho)
        out["half_life"] = hl
        out["status"] = "ok"
    return out


def unit_root_diagnostics(x: np.ndarray, name: str) -> dict:
    """ADF (null: unit root) and KPSS (null: level stationarity) on one log-price series."""
    x = np.asarray(x, dtype=float)
    out: dict = {"series": name}
    try:
        adf = adfuller(x, maxlag=schwert_maxlag(len(x)), regression="c", autolag="AIC", result_object=False)
        out["adf_stat"], out["adf_pvalue"] = float(adf[0]), float(adf[1])
    except Exception as exc:  # constant input etc.
        out["adf_error"] = str(exc)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            k = kpss(x, regression="c", nlags="auto", result_object=False)
        out["kpss_stat"], out["kpss_pvalue"] = float(k[0]), float(k[1])
        if any("InterpolationWarning" in type(w.message).__name__ or "p-value" in str(w.message) for w in caught):
            out["kpss_pvalue_bounded"] = True  # table-bounded p-value (reported at 0.01 or 0.1)
    except Exception as exc:
        out["kpss_error"] = str(exc)
    return out


def fdr_by(pvalues: list[float], alpha: float) -> tuple[list[bool], list[float]]:
    """Benjamini-Yekutieli FDR across one formation-date family."""
    if not pvalues:
        return [], []
    reject, adj, _, _ = multipletests(np.asarray(pvalues, dtype=float), alpha=alpha, method="fdr_by")
    return [bool(r) for r in reject], [float(min(a, 1.0)) for a in adj]
