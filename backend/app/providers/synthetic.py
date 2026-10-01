"""SyntheticProvider: serves the canonical generator output unchanged."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import DEMO_DIR, file_sha256, load_universe
from ..data.canonical_generator import generate_demo
from ..validation.validate import SYNTHETIC_DEMO, DataValidationError
from .base import Dataset, Provider, build_dataset


class SyntheticProvider(Provider):
    name = "synthetic"
    mode = SYNTHETIC_DEMO

    def __init__(self, directory: Path = DEMO_DIR):
        self.directory = Path(directory)
        self.csv = self.directory / "canonical_demo.csv"
        self.manifest_path = self.directory / "canonical_demo_manifest.json"
        self._dataset: Dataset | None = None

    def ensure(self) -> None:
        if not self.csv.exists() or not self.manifest_path.exists():
            generate_demo(self.directory)

    def _manifest(self) -> dict:
        self.ensure()
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def load_dataset(self) -> Dataset:
        if self._dataset is None:
            manifest = self._manifest()
            actual = file_sha256(self.csv)
            if actual != manifest["csv_sha256"]:
                raise DataValidationError(
                    "canonical_demo.csv hash does not match its manifest; regenerate with "
                    "`make generate` (cross-platform float serialisation may differ)")
            frame = pd.read_csv(self.csv, dtype={"symbol": str, "date": str})
            uni = load_universe("universe_synthetic.yaml")
            manifest = manifest | {
                "source": "canonical_synthetic_v1 (build kit section N)",
                "vendor": "none - generated",
                "timezone": "not applicable (synthetic weekday sessions)",
                "price_basis": "synthetic_no_actions",
                "corporate_actions": "none exist by construction",
                "permitted_usage": "synthetic test artifact; freely redistributable as part of this project",
                "validation_status": SYNTHETIC_DEMO,
            }
            self._dataset = build_dataset(frame, SYNTHETIC_DEMO, manifest, uni["groups"],
                                          uni["universe_version"], corporate_actions_accounted=True)
        return self._dataset

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
            return {"provider": self.name, "status": "ok", "mode": self.mode, "rows": int(len(ds.frame)),
                    "network": "not required"}
        except Exception as exc:  # pragma: no cover - surfaced in diagnostics
            return {"provider": self.name, "status": "error", "error": str(exc)}

    def freshness(self) -> dict:
        m = self._manifest()
        return {"last_date": m["end_date"], "note": "synthetic data has no real-world freshness"}
