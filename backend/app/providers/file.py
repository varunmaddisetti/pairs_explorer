"""FileProvider: imports a documented CSV/Parquet history supplied by a user or licensed source.

Safety:
* only datasets inside the configured import root are readable (no arbitrary paths);
* files are parsed as data with explicit dtypes - nothing is evaluated;
* the manifest must declare provenance, rights and adjustment treatment, and its content hash
  must match the data file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from ..config import IMPORT_DIR, file_sha256
from ..validation.validate import (
    HISTORY_COLUMNS, REAL_RESEARCH_VALIDATED, REAL_UNVALIDATED, RETURN_COHERENT_ADJUSTMENTS,
    SYNTHETIC_DEMO, DataValidationError,
)
from .base import Dataset, Provider, ProviderError, build_dataset

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
REQUIRED_MANIFEST = [
    "dataset_id", "source", "retrieved_at", "timezone", "price_basis", "corporate_actions",
    "permitted_usage", "retention", "identity_verified", "corporate_actions_accounted",
    "data_sha256", "universe_version", "groups",
]
DTYPES = {"symbol": "string", "exchange": "string", "series": "string", "date": "string",
          "provider": "string", "adjustment_status": "string", "dataset_id": "string"}


class FileProvider(Provider):
    name = "file"

    def __init__(self, dataset_name: str, import_root: Path = IMPORT_DIR):
        if not NAME_RE.match(dataset_name or ""):
            raise ProviderError("dataset name must be a simple folder name (letters, digits, _ or -)")
        root = Path(import_root).resolve()
        target = (root / dataset_name).resolve()
        if root not in target.parents:
            raise ProviderError("dataset path escapes the import directory")
        self.root = target
        self._dataset: Dataset | None = None
        self.mode = REAL_UNVALIDATED

    def _data_file(self) -> Path:
        for name in ("data.parquet", "data.csv"):
            p = self.root / name
            if p.is_file() and not p.is_symlink():
                return p
        raise ProviderError(f"no data.csv or data.parquet in {self.root.name}")

    def _manifest(self) -> dict:
        p = self.root / "manifest.json"
        if not p.is_file():
            raise ProviderError("manifest.json is required for file imports")
        m = json.loads(p.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED_MANIFEST if k not in m]
        if missing:
            raise DataValidationError(f"manifest missing required fields: {missing}")
        return m

    def load_dataset(self) -> Dataset:
        if self._dataset is not None:
            return self._dataset
        m = self._manifest()
        path = self._data_file()
        if file_sha256(path) != m["data_sha256"]:
            raise DataValidationError("data file hash does not match manifest data_sha256")
        if path.suffix == ".csv":
            frame = pd.read_csv(path, dtype=DTYPES, keep_default_na=True, engine="c")
        else:
            frame = pd.read_parquet(path)
        unexpected = [c for c in frame.columns if c not in HISTORY_COLUMNS]
        if unexpected:
            raise DataValidationError(f"unexpected columns: {unexpected}")
        claimed = m.get("validation_status", REAL_UNVALIDATED)
        if claimed == SYNTHETIC_DEMO:
            raise DataValidationError("file imports are real-data routes; synthetic data uses SyntheticProvider")
        # Validate as REAL_UNVALIDATED first; promotion is computed, never taken on trust.
        ds = build_dataset(frame, REAL_UNVALIDATED, m, m["groups"], m["universe_version"],
                           corporate_actions_accounted=bool(m["corporate_actions_accounted"]))
        adj = set(ds.frame["adjustment_status"].unique())
        promotable = (
            claimed == REAL_RESEARCH_VALIDATED
            and ds.report.ok
            and bool(m["identity_verified"])
            and bool(m["corporate_actions_accounted"])
            and adj <= RETURN_COHERENT_ADJUSTMENTS
            and not any(i.code in ("missing_sessions", "unknown_adjustment", "stale") for i in ds.report.issues)
        )
        ds.mode = REAL_RESEARCH_VALIDATED if promotable else REAL_UNVALIDATED
        ds.manifest = m | {"validation_status": ds.mode,
                           "promotion_note": None if promotable else
                           "kept REAL_UNVALIDATED: identity, adjustment, corporate-action or session checks incomplete"}
        self.mode = ds.mode
        self._dataset = ds
        return ds

    def symbols(self) -> list[str]:
        return self.load_dataset().symbols

    def history(self, symbol: str) -> pd.DataFrame:
        f = self.load_dataset().frame
        return f[f["symbol"] == symbol].reset_index(drop=True)

    def metadata(self) -> dict:
        return self.load_dataset().manifest

    def health(self) -> dict:
        try:
            ds = self.load_dataset()
            return {"provider": self.name, "status": "ok", "mode": ds.mode, "rows": int(len(ds.frame))}
        except Exception as exc:
            return {"provider": self.name, "status": "error", "error": str(exc)}

    def freshness(self) -> dict:
        ds = self.load_dataset()
        return {"last_date": ds.frame["date"].max().strftime("%Y-%m-%d"),
                "retrieved_at": ds.manifest.get("retrieved_at")}
