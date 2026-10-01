"""Experiment registry (DuckDB). Counts every run, flags exploratory and holdout-touching runs."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .config import RUNTIME_DIR

_LOCK = threading.Lock()


class Registry:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or RUNTIME_DIR / "experiments.duckdb")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, duckdb.connect(str(self.path)) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS experiments (
                run_id VARCHAR PRIMARY KEY, created_at TIMESTAMP, kind VARCHAR, pair VARCHAR,
                source_mode VARCHAR, dataset_hash VARCHAR, params_hash VARCHAR, exploratory BOOLEAN,
                touches_holdout BOOLEAN, result_sha256 VARCHAR, manifest_json VARCHAR)""")

    def log(self, kind: str, pair: str, manifest: dict, result_sha256: str, touches_holdout: bool) -> str:
        run_id = uuid.uuid4().hex[:12]
        with _LOCK, duckdb.connect(str(self.path)) as con:
            con.execute("INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                run_id, datetime.now(timezone.utc).replace(tzinfo=None), kind, pair, manifest["source_mode"],
                manifest["dataset_content_sha256"], manifest["params_sha256_16"],
                bool(manifest["non_default_params"]), touches_holdout, result_sha256,
                json.dumps(manifest, default=str)])
        return run_id

    def summary(self) -> dict:
        with _LOCK, duckdb.connect(str(self.path)) as con:
            rows = con.execute("""SELECT count(*), count(DISTINCT params_hash),
                                  coalesce(sum(CASE WHEN exploratory THEN 1 ELSE 0 END),0),
                                  coalesce(sum(CASE WHEN touches_holdout THEN 1 ELSE 0 END),0)
                                  FROM experiments""").fetchone()
            recent = con.execute("""SELECT run_id, created_at, kind, pair, source_mode, params_hash, exploratory,
                                    touches_holdout, result_sha256 FROM experiments
                                    ORDER BY created_at DESC LIMIT 20""").fetchall()
        cols = ["run_id", "created_at", "kind", "pair", "source_mode", "params_hash", "exploratory",
                "touches_holdout", "result_sha256"]
        return {"total_runs": rows[0], "distinct_parameter_versions": rows[1], "exploratory_runs": rows[2],
                "runs_touching_holdout": rows[3],
                "recent": [dict(zip(cols, [str(v) if i == 1 else v for i, v in enumerate(r)])) for r in recent]}

    def manifest(self, run_id: str) -> dict | None:
        with _LOCK, duckdb.connect(str(self.path)) as con:
            r = con.execute("SELECT manifest_json FROM experiments WHERE run_id = ?", [run_id]).fetchone()
        return json.loads(r[0]) if r else None
