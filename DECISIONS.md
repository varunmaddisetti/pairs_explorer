# Decisions

Routine decisions taken autonomously (build kit section B). Material ones are listed here.

| # | Decision | Reason |
|---|---|---|
| D1 | Python 3.12.3 via uv (`/usr/bin/python3.12`); system default 3.11 not used | spec default |
| D2 | Plotly (plotly.js-dist-min) for charts; server-side matplotlib for the PNG card | Plotly gives hover and responsive charts; a server-rendered card means the age gate applies to exports and the card does not depend on browser state |
| D3 | DuckDB for the experiment registry; Parquet/JSON caches under `data/cache/<mode>/<dataset>/<hash>` | no server DB; caches cannot collide across modes |
| D4 | One fold grid for the whole universe: fold k formation [63k, 63k+252), evaluation [63k+252, 63k+315) | all pairs in a family share formation dates, so BY families are well-defined |
| D5 | Final holdout = last 252 calendar sessions, needs ≥ 1 full development fold before it; with the demo data it aligns to folds 12–15 | spec |
| D6 | Quantities sized on slippage-adjusted execution prices so traded gross notional = G exactly | keeps G = 0.9E literal under the production slippage convention |
| D7 | Production friction = adverse price slippage + commission/levy fees; a labelled `simple_debit` mode exists for the 20-bps oracle | spec G4, no double counting |
| D8 | No entry fill on the final session of a block | a fill that the boundary exit would close the same day only creates costs |
| D9 | Cooldown: earliest re-entry fill = exit-fill session + 2 | "one complete trading session after exit" applied uniformly to open and close exits |
| D10 | Max holding: exit ordered at the close of the 20th held session (entry session = 1), filled next open | decisions are taken at closes; documented |
| D11 | Borrow accrues at each valuation on the previous short MV × calendar days / 365; same-date intervals = 0 days | ACT/365 on elapsed calendar time |
| D12 | Stress split: X bps = ½ slippage, ¼ commission, ¼ levy (base 20 bps = 10/5/5) | the 20-bps stress equals the base case |
| D13 | Long-only comparator: 45% + 45% of equity in A and B at the first evaluation open, held to the end, same costs | "explicitly described" comparison |
| D14 | Strict mode excludes folds with any missing session in the evaluation block (known in advance) | spec. This can only remove trades; non-strict mode handles gaps at runtime (cancel or halt) |
| D15 | Curated teaching and contrast examples selected by algorithm from development-period as-of refits plus reveals, never from generator labels or the holdout | avoids leaking construction ground truth; teaching = first eligible date with \|z\| ≥ 2 that later crossed the exit band without hitting ±3.5; contrast = eligible date with the largest later \|z\| ≥ 3.5 |
| D16 | The scanner's "current z" is the last formation residual under as-of parameters (in-sample to that window); walk-forward OOS z shown separately | spec "refit using the matching trailing formation window" |
| D17 | Real-data expected calendar = union of observed sessions until a verified NSE holiday calendar is added | no verified calendar available offline |
| D18 | Engle–Granger maxlag set explicitly to Schwert ceil(12(n/100)^¼) with AIC | explicit, documented lag selection; matches the statsmodels default rule |
| D19 | Win rate / profit factor require ≥ 5 closed trades; Sharpe requires ≥ 20 returns and non-zero sd; annualized return requires ≥ 252 sessions | avoid meaningless ratios |
| D20 | `cash_interest_annual` and `risk_free_annual` validated to be exactly 0 in v1 | no unstated financing benefit |
| D21 | Editable UI parameters limited to thresholds, holding, sizing and costs; formation/FDR settings are fixed | prevents casual search over the inferential procedure |
| D22 | No optional AI explanation adapter was built | spec: core first; deterministic template is mandatory and sufficient |
| D23 | Single-theme (light) UI; system font stacks only | works fully offline; no external font requests |
