"""Experiment manifests and reproducibility helpers."""
from __future__ import annotations

import hashlib
import importlib.metadata as im
import json
import platform
import subprocess
from datetime import datetime, timezone
from typing import Any

from .config import ROOT, SCHEMA_VERSION, ResearchParams

TRACKED = ["numpy", "pandas", "scipy", "statsmodels", "duckdb", "pyarrow", "fastapi", "pydantic",
           "matplotlib", "mcp"]
VOLATILE_KEYS = {"run_time", "run_id", "created_at", "elapsed_seconds", "git_commit", "retrieved_at"}


def dependency_versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for name in TRACKED:
        try:
            out[name] = im.version(name)
        except im.PackageNotFoundError:
            out[name] = "not installed"
    return out


def git_commit() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True,
                               timeout=5).stdout.strip()
        return r.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def stable_hash(obj: Any) -> str:
    """Hash of a result with run timestamps stripped and floats rounded to 10 significant digits."""
    def norm(o: Any) -> Any:
        if isinstance(o, float):
            return float(f"{o:.10g}")
        if isinstance(o, dict):
            return {k: norm(v) for k, v in o.items()}
        if isinstance(o, list):
            return [norm(v) for v in o]
        return o
    payload = json.dumps(norm(strip_volatile(obj)), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def experiment_manifest(*, kind: str, ds, params: ResearchParams, observation_cutoff: str,
                        extra: dict | None = None) -> dict:
    return {
        "kind": kind,
        "schema_version": SCHEMA_VERSION,
        "dataset_id": ds.dataset_id,
        "dataset_content_sha256": ds.content_hash,
        "dataset_file_sha256": ds.manifest.get("csv_sha256") or ds.manifest.get("data_sha256"),
        "source_mode": ds.mode,
        "universe_version": ds.universe_version,
        "observation_cutoff": observation_cutoff,
        "config_version": params.config_version,
        "params_sha256_16": params.hash(),
        "params": params.model_dump(),
        "non_default_params": params.differs_from_defaults(),
        "seed": params.demo_seed,
        "dependency_versions": dependency_versions(),
        "git_commit": git_commit(),
        "run_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    } | (extra or {})
