# File import route (FileProvider)

Place each licensed/user dataset in its own folder: `data/imports/<name>/` (letters, digits, `_`, `-`).
Contents of this directory other than this README are git-ignored: **never commit market data you do not have rights to redistribute.**

```
data/imports/<name>/
  data.csv            # or data.parquet
  manifest.json
```

`data.csv` columns (exactly): `symbol, exchange, series, date (YYYY-MM-DD), open, high, low, close, volume, provider, adjustment_status, dataset_id`.
`adjustment_status` ∈ `raw_unadjusted | split_bonus_adjusted | total_return_adjusted | unknown` (`synthetic_no_actions` is rejected for imports).

`manifest.json` required fields: `dataset_id, source, retrieved_at, timezone, price_basis, corporate_actions, permitted_usage, retention,
identity_verified, corporate_actions_accounted, data_sha256 (sha256 of the data file), universe_version, groups ({group: [symbols]})`;
optional `validation_status` (`REAL_RESEARCH_VALIDATED` is only *granted* if every check passes: identity verified, corporate actions accounted,
coherent adjustment, no missing sessions/unknown adjustment/staleness). Otherwise the dataset stays `REAL_UNVALIDATED` and backtests are
labelled PRICE-ONLY DIAGNOSTIC.

Run: `PDE_SOURCE=file PDE_FILE_DATASET=<name> make demo`. Files are parsed as data only; paths outside `data/imports/` are refused.
