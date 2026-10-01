"""Configuration loading, versioning and hashing."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DEMO_DIR = DATA_DIR / "demo"
IMPORT_DIR = DATA_DIR / "imports"
SNAPSHOT_DIR = DATA_DIR / "provider_snapshots"
RUNTIME_DIR = Path(os.environ.get("PDE_RUNTIME_DIR", DATA_DIR / "runtime"))
CACHE_DIR = Path(os.environ.get("PDE_CACHE_DIR", DATA_DIR / "cache"))
SCHEMA_VERSION = "history_schema_v1"


class ResearchParams(BaseModel):
    """Research/backtest parameters. Defaults mirror config/research_defaults.yaml."""

    config_version: str = "research_defaults_v1"
    formation_window: int = Field(252, ge=60, le=2000)
    evaluation_block: int = Field(63, ge=5, le=504)
    calibration_window: int = Field(60, ge=20, le=2000)
    final_holdout: int = Field(252, ge=0, le=5000)
    entry_z: float = Field(2.0, gt=0, le=10)
    entry_z_max: float = Field(3.5, gt=0, le=20)
    exit_z: float = Field(0.5, ge=0, le=10)
    adverse_z: float = Field(3.5, gt=0, le=20)
    max_holding: int = Field(20, ge=1, le=500)
    cooldown_sessions: int = Field(1, ge=0, le=100)
    fdr_method: Literal["fdr_by"] = "fdr_by"
    fdr_alpha: float = Field(0.05, gt=0, lt=1)
    beta_min: float = Field(0.1, gt=0)
    beta_max: float = Field(5.0, gt=0)
    half_life_min: float = Field(2.0, gt=0)
    half_life_max: float = Field(60.0, gt=0)
    starting_equity: float = Field(100000.0, gt=0)
    gross_exposure: float = Field(0.90, gt=0, le=1.0)
    commission_bps: float = Field(5.0, ge=0, le=500)
    slippage_bps: float = Field(10.0, ge=0, le=500)
    levy_bps: float = Field(5.0, ge=0, le=500)
    borrow_annual: float = Field(0.05, ge=0, le=1.0)
    cash_interest_annual: float = Field(0.0, ge=0, le=0.0)  # fixed at zero in v1
    risk_free_annual: float = Field(0.0, ge=0, le=0.0)      # fixed at zero in v1
    friction_mode: Literal["price_slippage", "simple_debit"] = "price_slippage"
    rolling_corr_window: int = Field(63, ge=10, le=504)
    stress_bps: list[float] = [5, 20, 50]
    demo_seed: int = 20261001
    public_history_buffer_days: int = 45

    @model_validator(mode="after")
    def _check(self) -> "ResearchParams":
        if self.calibration_window > self.formation_window:
            raise ValueError("calibration_window must not exceed formation_window")
        if not (self.exit_z < self.entry_z < self.entry_z_max <= self.adverse_z):
            raise ValueError("require exit_z < entry_z < entry_z_max <= adverse_z")
        if self.beta_min >= self.beta_max:
            raise ValueError("beta_min must be < beta_max")
        if self.half_life_min >= self.half_life_max:
            raise ValueError("half_life_min must be < half_life_max")
        return self

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))

    def hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()[:16]

    def differs_from_defaults(self) -> list[str]:
        base = load_default_params().model_dump()
        return sorted(k for k, v in self.model_dump().items() if base.get(k) != v)


def _yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def load_default_params() -> ResearchParams:
    return ResearchParams(**_yaml("research_defaults.yaml"))


def load_universe(name: str) -> dict:
    return _yaml(name)


def load_display_policy() -> dict:
    return _yaml("display_policy.yaml")


def load_nse_mapping() -> dict:
    return _yaml("nse_mapping.yaml")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
