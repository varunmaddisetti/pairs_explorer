# Build plan — Pairs Divergence Explorer

Source of requirements: `Pairs_Divergence_Explorer_Build_Kit.md` v1.0 (MASTER BUILD PROMPT, sections A–N).

## Environment found at start (2026-10-01)
- Linux container, empty git repo on branch `claude/pairs-divergence-explorer-build-ytkdso`.
- Python 3.12.3 (`/usr/bin/python3.12`; default `python3` is 3.11 so uv pins 3.12), uv 0.8.17.
- Node 22.22.0 / npm 10.9.4; Playwright Chromium build 1194 at `/opt/pw-browsers`.
- Network: PyPI + npm reachable. `mcp.nseindia.in`, `www.nseindia.com`, `www.sebi.gov.in`,
  `www.statsmodels.org` **denied by the environment egress policy (HTTP 403 at proxy CONNECT)**.

## Work order (section K)
1. Inspect env; BUILD_PLAN / BUILD_STATUS.  
2. Canonical generator (verbatim), schema, validation, providers (synthetic/file).  
3. Regression / spread / Engle–Granger / FDR / half-life / descriptive analytics + reference tests.  
4. Event-driven fold backtest + explicit cash/position ledger + oracles.  
5. FastAPI service, React/Vite UI: Explore, Pair, Playback, Backtest, Method & Data.  
6. NSE MCP adapter (discovery snapshot, bounded retries, schema-checked mapping) + import route.  
7. PNG research card, docs, launcher (`make demo`, `start_demo.sh/.ps1`), Docker Compose.  
8. pytest suite + Playwright critical flow + desktop/mobile screenshots.  
9. Acceptance report, MODEL_COMPARISON.json, source archive.
