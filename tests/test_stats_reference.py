"""Gate J7: agreement with separately invoked trusted implementations; invalid states."""
import numpy as np
import pytest
from scipy import stats as sps
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.adfvalues import mackinnoncrit, mackinnonp
from statsmodels.tsa.stattools import adfuller

from app.analytics.stats import (engle_granger, fdr_by, fit_spread, half_life, ols_alpha_beta,
                                 schwert_maxlag)


@pytest.fixture(scope="module")
def frozen(ds):
    p = ds.panel("S_BANK_A", "S_BANK_B").iloc[:252]
    return np.log(p["close_a"].to_numpy()), np.log(p["close_b"].to_numpy())


def test_regression_matches_scipy_and_statsmodels(frozen):
    la, lb = frozen
    alpha, beta, resid, rank, r2 = ols_alpha_beta(la, lb)
    lr = sps.linregress(lb, la)
    assert alpha == pytest.approx(lr.intercept, rel=1e-10) and beta == pytest.approx(lr.slope, rel=1e-10)
    sm = OLS(la, add_constant(lb)).fit()
    assert np.allclose(resid, sm.resid) and r2 == pytest.approx(sm.rsquared)


def test_spread_mu_sigma_definition(frozen):
    la, lb = frozen
    m = fit_spread(la, lb, 60, 252)
    s = la - m.alpha - m.beta * lb
    assert m.mu == pytest.approx(s[-60:].mean()) and m.sigma == pytest.approx(s[-60:].std(ddof=1))
    z = m.z(la, lb)
    assert z[-1] == pytest.approx((s[-1] - s[-60:].mean()) / s[-60:].std(ddof=1))


def test_engle_granger_matches_independent_two_step(frozen):
    la, lb = frozen
    eg = engle_granger(la, lb)
    resid = OLS(la, add_constant(lb)).fit().resid
    maxlag = schwert_maxlag(len(la))
    adf = adfuller(resid, maxlag=maxlag, autolag="aic", regression="n", result_object=False)
    assert eg["statistic"] == pytest.approx(adf[0], rel=1e-10)
    assert eg["pvalue"] == pytest.approx(mackinnonp(adf[0], regression="c", N=2), rel=1e-10)
    crit = mackinnoncrit(N=2, regression="c", nobs=len(la) - 1)
    assert [eg["crit_1pct"], eg["crit_5pct"], eg["crit_10pct"]] == pytest.approx(list(crit))
    assert eg["maxlag"] == 16 and eg["nobs"] == 252


def test_engle_granger_residual_adf_with_constant_is_not_the_reported_pvalue(frozen):
    la, lb = frozen
    resid = OLS(la, add_constant(lb)).fit().resid
    generic = adfuller(resid, regression="c", autolag="AIC", result_object=False)[1]
    assert generic != pytest.approx(engle_granger(la, lb)["pvalue"], rel=1e-3)


def by_manual(p):
    p = np.asarray(p, float); m = len(p)
    c = np.sum(1.0 / np.arange(1, m + 1))
    order = np.argsort(p)
    adj = np.empty(m)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * m * c / rank)
        adj[i] = prev
    return np.minimum(adj, 1.0)


@pytest.mark.parametrize("pv", [[0.001, 0.02, 0.04, 0.5], [0.3, 0.01], [0.049], [0.004, 0.004, 0.9, 0.012, 0.03]])
def test_fdr_by_matches_manual_formula(pv):
    reject, adj = fdr_by(pv, 0.05)
    assert adj == pytest.approx(list(by_manual(pv)))
    assert reject == [a <= 0.05 for a in adj]


def test_invalid_pairs(frozen):
    la, lb = frozen
    assert fit_spread(la, la.copy(), 60, 252).reasons == ["duplicate_series"]
    assert fit_spread(la, np.full(252, 4.0), 60, 252).reasons == ["constant_series"]
    rng = np.random.default_rng(0)
    near = fit_spread(la, la + 0.3 + rng.normal(0, 1e-9, 252), 60, 252)
    assert not near.valid and "near_identical" in near.reasons[0]
    assert fit_spread(la[:100], lb[:100], 60, 252).reasons[0].startswith("insufficient_observations")
    bad = la.copy(); bad[5] = np.nan
    assert fit_spread(bad, lb, 60, 252).reasons == ["non_finite_values"]


def test_degenerate_sigma_when_calibration_window_is_flat():
    rng = np.random.default_rng(1)
    lb = np.cumsum(rng.normal(0, 0.01, 252)) + 5
    lb[192:] = lb[191]                       # both legs flat through the 60-session calibration window
    la = 1.0 + 0.8 * lb + rng.normal(0, 0.01, 252)
    la[192:] = la[191]
    m = fit_spread(la, lb, 60, 252)
    assert not m.valid and m.reasons == ["degenerate_spread_sigma"]


def test_half_life_states():
    rng = np.random.default_rng(2)
    e = rng.normal(0, 1, 2000)
    ar = np.zeros(2000)
    for t in range(1, 2000):
        ar[t] = 0.9 * ar[t - 1] + e[t]
    hl = half_life(ar)
    ref = OLS(np.diff(ar), add_constant(ar[:-1])).fit().params       # independent reference regression
    assert hl["status"] == "ok" and hl["kappa"] == pytest.approx(ref[1], rel=1e-10)
    assert hl["half_life"] == pytest.approx(-np.log(2) / np.log(1 + ref[1]), rel=1e-10)
    assert 0.8 < hl["rho"] < 0.95
    explosive = np.cumprod(np.full(100, 1.05))
    assert half_life(explosive)["status"].startswith("non_reverting") and half_life(explosive)["half_life"] is None
    osc = np.zeros(300)
    for t in range(1, 300):
        osc[t] = -0.6 * osc[t - 1] + e[t]
    assert half_life(osc)["status"].startswith("oscillating")
    assert half_life(ar[:10])["status"] == "insufficient_data"
    assert half_life(np.zeros(100))["status"] == "degenerate"
