"""`make refresh`: explicit, bounded refresh of the configured permitted source (NSE MCP).

Steps: discover tools on each documented endpoint (snapshot saved), validate the configured
mapping against the snapshot, then fetch a SMALL validation sample (<= 2 symbols, serial, paced).
Never runs at startup, never substitutes synthetic data, logs every attempt honestly.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import SNAPSHOT_DIR  # noqa: E402
from app.providers.base import ProviderError, ProviderNotConfigured  # noqa: E402
from app.providers.nse_mcp import NseMcpProvider  # noqa: E402

LOG = SNAPSHOT_DIR / "refresh_log.jsonl"


def log(entry: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds")} | entry
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    print(json.dumps(entry, indent=2, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", nargs="*", default=["HDFCBANK", "ICICIBANK"], help="validation sample (max 2)")
    args = ap.parse_args()
    prov = NseMcpProvider()
    health = prov.health()
    (SNAPSHOT_DIR / "nse_health_redacted.json").write_text(json.dumps(health, indent=2, default=str) + "\n")
    reachable = [k for k, v in health["endpoints"].items() if v["status"] == "reachable"]
    if not reachable:
        log({"op": "discovery", "outcome": "unavailable", "endpoints": health["endpoints"],
             "detail": "No NSE MCP endpoint reachable; no data fetched; synthetic data NOT substituted."})
        return 2
    try:
        end = date.today()
        start = end - timedelta(days=30)
        for sym in args.sample[:2]:
            df = prov.fetch_history(sym, start.isoformat(), end.isoformat())
            log({"op": "validation_sample", "outcome": "ok", "symbol": sym, "rows": len(df),
                 "mode": "REAL_UNVALIDATED", "note": "sample only; not written to the research dataset"})
    except ProviderNotConfigured as exc:
        log({"op": "history", "outcome": "not_configured", "detail": str(exc),
             "next_step": "inspect data/provider_snapshots/nse_*_tools.json and fill config/nse_mapping.yaml"})
        return 3
    except ProviderError as exc:
        log({"op": "history", "outcome": type(exc).__name__, "detail": str(exc)[:300]})
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
