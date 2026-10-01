"""Re-run a backtest from an exported manifest.json and compare the timestamp-stripped result hash."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backtest.run import run_pair_backtest  # noqa: E402
from app.config import ResearchParams  # noqa: E402
from app.providers.synthetic import SyntheticProvider  # noqa: E402


def main(path: str, expected: str | None = None) -> int:
    man = json.loads(Path(path).read_text(encoding="utf-8"))
    if man["source_mode"] != "SYNTHETIC_DEMO":
        print("This helper reproduces synthetic runs; real-data runs need the same licensed file import.")
        return 2
    ds = SyntheticProvider().load_dataset()
    if ds.content_hash != man["dataset_content_sha256"]:
        print("dataset content hash differs from the manifest; cannot reproduce")
        return 1
    a, b = man["pair"].split("/")
    res = run_pair_backtest(ds, a, b, ResearchParams(**man["params"]), strict=man["strict"])
    print(f"result_sha256 {res['result_sha256']}")
    readme = Path(path).with_name("README.txt")
    if expected is None and readme.exists():
        for line in readme.read_text().splitlines():
            if line.startswith("Result sha256"):
                expected = line.split(":")[-1].strip()
    if expected:
        print("MATCH" if expected == res["result_sha256"] else f"MISMATCH (expected {expected})")
        return 0 if expected == res["result_sha256"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
