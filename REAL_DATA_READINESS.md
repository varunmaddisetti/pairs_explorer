# Real-data readiness report

**Verdict: NOT READY. No real NSE data has been retrieved, validated or displayed.** The synthetic demo is complete and separate from this report.

## What was attempted (actual evidence)

| When (UTC) | Action | Result |
|---|---|---|
| 2026-10-01 17:45 | `curl` POST `initialize` to `https://mcp.nseindia.in/bhavcopy/cm/mcp` | proxy CONNECT **403**: the host is denied by this build environment's egress policy |
| 2026-10-01 17:45 | `curl` `https://mcp.nseindia.in/cmmkt/mcp`, `https://www.nseindia.com/nse-mcp` | proxy CONNECT **403** |
| 2026-10-01 17:46 | `https://www.sebi.gov.in/`, `https://www.statsmodels.org/` | proxy CONNECT **403** (primary sources could not be read) |
| 2026-10-01 18:13 | `make refresh` → `NseMcpProvider.health()` via MCP Python SDK 2.2.0 (streamable HTTP) | both endpoints `ProviderPermissionError: ProxyError: 403 Forbidden`. Classified as permission/policy, **not retried**, no data fetched, no synthetic substitution. Logged in `data/provider_snapshots/refresh_log.jsonl` and `nse_health_redacted.json` |

The denial came from the build environment's network policy, not necessarily from NSE. Whether NSE's endpoints accept anonymous MCP
sessions, which tools they expose, and their published limits are therefore **unknown**.

## What is implemented and tested (with mocks)

* `NseMcpProvider`: MCP SDK transport; tool discovery with a snapshot file and schema hash; schema-change detection; a mapping
  (`config/nse_mapping.yaml`) that must name a discovered tool, where every argument must exist in the discovered input schema and every
  required argument must be mapped; serial pacing (2 s); bounded retries (3 attempts, 1 s/2 s backoff) for transient errors only; no retry
  on 401/403/407/451 or proxy denial; malformed responses raise a schema error; cancellation; redacted health; output labelled
  `REAL_UNVALIDATED` with `adjustment_status = unknown`. Covered by `tests/test_providers.py` (9 NSE-adapter tests + 2 FileProvider tests).
* `FileProvider` import route for licensed CSV/Parquet with manifest validation and computed (never trusted) promotion to
  `REAL_RESEARCH_VALIDATED`.
* Validation, age gate and display-permission logic shared with the synthetic path.

## Exact remaining steps

1. **Network**: allow `mcp.nseindia.in` (and `www.nseindia.com`, `www.sebi.gov.in` for primary-source checks) in the environment's network
   settings, or run `make refresh` on a machine with ordinary internet access.
2. **Terms**: read https://www.nseindia.com/nse-mcp and the NSE data policy, and record permitted use, rate limits and retention in DATA_RIGHTS.md.
3. **Discovery**: `make refresh` writes `data/provider_snapshots/nse_bhavcopy_cm_tools.json` / `nse_cmmkt_tools.json`. Inspect the actual tool
   names and input/output schemas.
4. **Mapping**: fill `history_endpoint`, `history_tool`, `arguments`, `response_fields` in `config/nse_mapping.yaml` from the snapshot (not from
   blog posts). `make refresh` then fetches a 2-symbol, 30-day validation sample only.
5. **Identity**: verify current and historical symbol/series identity for the 20 candidates in `config/universe_nse_candidates.yaml`
   (`identity_verified: false` today). Record renames and mergers. Disclose survivorship bias: these are current names, not historical index members.
6. **Corporate actions**: bhavcopy prices are presumed raw. Obtain split/bonus/dividend/demerger records, build adjusted series or
   action-aware accounting, and set `adjustment_status` accordingly. Until then backtests are labelled **PRICE-ONLY DIAGNOSTIC** (enforced in code).
7. **Calendar**: add a verified NSE trading-holiday calendar so missing sessions are detected against exchange sessions rather than the union of
   observed dates.
8. **Bulk history**: only after steps 3–7, download the universe serially within published limits, store as a FileProvider dataset with a
   manifest (`data/imports/<name>/`), and rerun validation. Promotion to `REAL_RESEARCH_VALIDATED` is computed by the code.
9. **Public display**: remains disallowed until a separate permission review updates `config/display_policy.yaml`. Technical success does not change it.

## Not verified

Real data availability, NSE tool schemas, rate limits, symbol identity, corporate-action coverage, borrow availability and execution feasibility.
