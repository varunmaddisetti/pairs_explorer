# Methodology

All numbers are produced by deterministic backend code (`backend/app`). The UI renders backend values; the explanation text is a fixed
template filled with those values. Defaults (`config/research_defaults.yaml`, `research_defaults_v1`) are prototype choices, **not**
claimed to be optimal.

## 1. Data and calendar

* Common schema: `symbol, exchange, series, date, open, high, low, close, volume, provider, adjustment_status, dataset_id`.
* Validation (`validation/validate.py`): ISO dates, duplicates, positive finite prices, OHLC bounds, nonnegative volume, symbol format,
  identity (exchange/series) changes, off-calendar rows, history length, staleness (real data), unknown adjustment, missing sessions.
* Mixed synthetic/real rows, multiple dataset ids, or labels contradicting the declared mode are **rejected**.
* Synthetic calendar = weekdays only (`pd.bdate_range`), *not* an NSE holiday calendar. Real data: expected sessions = union of sessions
  observed for any symbol (a day with no trades in any symbol is treated as a holiday). A verified NSE holiday calendar is not bundled.
* **No forward filling.** Pair panels keep NaN for missing sessions. A formation window with a missing session is skipped
  (`missing_sessions_in_formation`); in strict mode an evaluation block with a missing session is not traded
  (`missing_sessions_in_evaluation_block(strict)`). This exclusion knows about gaps inside the coming block, which is a data-availability
  screen that can only remove trades. In non-strict mode the engine instead cancels an entry whose fill is missing and **halts** with an
  unresolved exposure if a held position cannot be valued.

## 2. Spread model (section F2)

Orientation is lexicographic: A < B. With `n = 252` formation sessions:

```
log P_A,t = α + β log P_B,t + ε_t         (OLS via least squares)
s_t = log P_A,t − α − β log P_B,t
μ = mean(s over last 60 formation sessions);  σ = sd(same, ddof = 1)
z_t = (s_t − μ) / σ
```

Invalid pairs (reported, never scored): insufficient observations, non-finite values, constant series, exact duplicates,
near-identical series (log-level R² > 1 − 1e−10), rank-deficient regression, σ < 1e−8.

## 3. Inference

* **Engle–Granger**: `statsmodels.tsa.stattools.coint(logA, logB, trend="c", method="aeg", maxlag=ceil(12·(n/100)^¼) (=16 for n=252), autolag="aic")`.
  Null = no cointegration. Statistic, MacKinnon p-value, 1/5/10% critical values, nobs and maxlag are stored. Verified in tests to equal an
  independently invoked `adfuller(resid, regression="n")` + `mackinnonp(N=2)`. A generic ADF-with-constant p-value on residuals is **not**
  used (a test asserts it differs).
* **Family correction**: at each formation date, all valid predefined same-industry candidates are tested, and
  `multipletests(p, alpha=0.05, method="fdr_by")` is applied across that family. Raw/adjusted p, family size and skipped tests are shown. Levels are
  never relaxed; zero eligible pairs is displayed as such. BY is a nominal procedure under assumptions, not a convergence probability, and does
  not remove all model-selection bias; every backtest run is logged (DuckDB registry) with parameter hash, exploratory flag and holdout use.
* **Unit-root diagnostics**: ADF (null unit root) and KPSS (null level stationarity, p-value table-bounded to [0.01, 0.1]) on each log price.
  Non-rejection does not prove a unit root.
* **Half-life**: OLS `Δs_t = c + κ s_{t−1} + e_t` on the 252 formation residuals, ρ = 1 + κ. Half-life = −ln 2 / ln ρ only for 0 < ρ < 1;
  otherwise status `non_reverting(rho>=1)`, `oscillating(rho<=0)`, `degenerate` or `insufficient_data`, never clipped.
* **Eligibility**: BY rejection at 5% AND 0.1 ≤ β ≤ 5.0 AND 2 ≤ half-life ≤ 60 sessions AND data complete.
* **Stability**: β from every prior fold formation window is displayed; warnings when β moves > 25% between consecutive windows, changes sign,
  or has max/min > 1.5 over four windows (explanatory heuristics, **no structural-break test is implemented**).
* Labels kept separate: relationship evidence, observed divergence, data quality, execution assumptions. No combined confidence score.
  Scanner ranking = |z| among eligible pairs, descriptive only.

## 4. Folds, timing and holdout (section G1)

* Fold k: formation = calendar indices [63k, 63k+252), evaluation = [63k+252, 63k+315). The canonical 1,260 sessions give 16 folds.
* Final holdout = last 252 sessions (index ≥ 1008 = folds 12–15), reported separately. Settings were fixed before it was examined. Any
  non-default run is labelled *exploratory* and logged. Rolling formation inside the holdout uses only earlier observations.
* Parameters (selection, α, β, μ, σ) are frozen for the evaluation block. No refit mid-trade.
* A signal observed at close t fills at open t+1. The first decision uses the last formation close and may fill at the first evaluation open.
* No new entry is filled on the final session of a block. Open positions are flattened at the final block close (scheduled
  `fold_boundary` exit, costs charged).
* Point-in-time playback refits on the trailing 252 sessions ending at the as-of date. The scanner, explanation and "what changed" use only
  those data. Reveals freeze the as-of parameters and are shown only on request.

## 5. Signals and exits (section G2), β > 0

| State | Rule |
|---|---|
| Long spread (long A, short B) | −3.5 < z ≤ −2.0 |
| Short spread (short A, long B) | 2.0 ≤ z < 3.5 |
| Convergence exit | long: z ≥ −0.5; short: z ≤ +0.5 (direction-specific, catches jumps across the mean) |
| Adverse exit | long: z ≤ −3.5; short: z ≥ +3.5 |
| Max holding | ordered at the close of the 20th held session (entry session counts as 1); fills next open |

Priority at a close: data/model invalid → adverse → max holding → convergence. The fold-boundary exit is applied at the block's final close.
Exits are observed at the close and filled at the next open; thresholds are not stop prices, and gaps can make losses larger.
**Cooldown**: after an exit filled in session e (open or close), the earliest re-entry fill is session e+2, so one complete flat session separates them.
`holding_sessions` in the trade table counts entry-fill session through exit-fill session inclusive.

## 6. Sizing, ledger and costs (G3/G4)

* Pre-entry equity E (= cash when flat); G = 0.90 E; w_A = 1/(1+β), w_B = β/(1+β).
* Long spread: q_A = +G w_A / P_A,exec, q_B = −G w_B / P_B,exec (signs reversed for short). Quantities are sized on execution prices so traded
  gross notional equals G. They are frozen until exit, and fractional shares are allowed (research simplification). The weights are not
  dollar-neutral (unless β = 1) and not market-beta-neutral.
* Explicit ledger: every fill debits/credits cash; short proceeds remain cash and do not raise gross exposure. Equity = cash + Σ q·P (marked at
  each close; `equity_after` recorded per fill). P&L is share P&L, never z-score changes. A test reconciles every day of a real run.
* **Production friction (`price_slippage`)**: slippage 10 bps moves execution prices adversely (buy ×1.001, sell ×0.999); commission 5 bps +
  levies 5 bps are debited on |traded notional at execution price|. Slippage is never also charged as a fee; its cost is reported for
  information only.
* **Labelled equivalent (`simple_debit`)**: all friction is debited as a fee on reference-price notional; prices are not moved. Used by the 20-bps cost oracle.
* **Borrow**: 5% p.a., ACT/365, accrued at each valuation on the *previous* short market value for calendar days elapsed (Fri→Mon = 3 days).
  Intraday intervals (entry open → same-day close, or exit on the same date) accrue 0 days.
* Cash interest and financing: 0%, stated explicitly.
* Equity ≤ 0 → run marked insolvent and halted, outstanding exposure reported, annualized return undefined (null).
* Stress scenarios: 5/20/50 bps total per leg per fill (½ slippage, ¼ commission, ¼ levy), borrow held at the configured rate. These are
  sensitivity scenarios, not broker quotes. Borrow availability, SLB costs, margin and futures substitution are **NOT VERIFIED / not modelled**.

## 7. Metrics and comparators (G5)

`backend/app/backtest/metrics.py` defines each metric: net return; annualized return (only ≥ 252 sessions and positive end equity);
annualized volatility = sd(daily r, ddof=1)·√252; Sharpe = mean(r − 0)/sd·√252 (null if sd = 0 or < 20 returns); max drawdown; turnover =
traded notional / mean equity; win rate and profit factor only with ≥ 5 closed trades (profit factor also needs a loss). No NaN or infinity is
reported. Comparators: cash at 0%, the same signals at zero friction (gross), and a long-only 45%/45% A+B hold with the same cost convention.
Results are shown for development, final holdout and all evaluation. One pair sleeve is not a portfolio, and sleeves are never aggregated.

## 8. Reproducibility

Experiment manifests record dataset content hash and file hash, universe version, observation cutoff, config version, full parameters and hash,
non-default keys, source mode, dependency versions, seed, git commit and run time. `result_sha256` hashes folds/trades/fills/daily/metrics after
stripping volatile keys and rounding to 10 significant digits. Run bundles (`/api/backtest/{id}/bundle.zip`) contain manifest, params, metrics
and CSVs (CSV cells are guarded against formula injection). `scripts/reproduce_run.py manifest.json` reruns and compares hashes.
Caches are namespaced by mode/dataset id/content hash and parameter hash, so synthetic and real caches cannot collide.

## 9. Limitations

Synthetic data only has been validated end to end. There are no corporate actions, the calendar is weekday-only and there are four
constructed pairs. The generator's construction labels are kept in the manifest and Method page only. No inference, curated-example
selection or label uses them. A real-data study would face survivorship bias in the current-name candidate list. No all-market claims,
profitability claims or production-readiness claims are made.
