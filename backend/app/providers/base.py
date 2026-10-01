"""Provider abstraction and the in-memory Dataset used by analytics."""
from __future__ import annotations

import abc
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..validation.validate import (
    SYNTHETIC_DEMO, ValidationReport, expected_calendar, validate_history,
)


class ProviderError(RuntimeError):
    """Base provider failure."""


class ProviderNotConfigured(ProviderError):
    pass


class ProviderPermissionError(ProviderError):
    """Permission/authorisation failures: never retried."""


class ProviderTransientError(ProviderError):
    """Timeouts, connection resets, 5xx: retried with bounded backoff."""


class ProviderSchemaError(ProviderError):
    """Discovered tool schema or response shape does not match expectations."""


@dataclass
class Dataset:
    frame: pd.DataFrame                 # common history schema, date as Timestamp
    mode: str                           # SYNTHETIC_DEMO / REAL_UNVALIDATED / REAL_RESEARCH_VALIDATED
    manifest: dict[str, Any]
    report: ValidationReport
    groups: dict[str, list[str]]
    universe_version: str
    calendar: pd.DatetimeIndex = field(default=None)  # type: ignore[assignment]
    content_hash: str = ""
    corporate_actions_accounted: bool = False

    def __post_init__(self) -> None:
        if self.calendar is None:
            self.calendar, _ = expected_calendar(self.frame, self.mode)
        if not self.content_hash:
            self.content_hash = frame_hash(self.frame)
        self.uid = uuid.uuid4().hex  # per-instance token for in-memory caches

    @property
    def dataset_id(self) -> str:
        return str(self.frame["dataset_id"].iloc[0])

    @property
    def symbols(self) -> list[str]:
        return sorted(self.frame["symbol"].unique())

    @property
    def cache_namespace(self) -> str:
        # Synthetic and real caches can never collide: mode + dataset id + content hash.
        return f"{self.mode.lower()}/{self.dataset_id}/{self.content_hash[:16]}"

    def candidate_pairs(self) -> list[tuple[str, str, str]]:
        """Predefined same-industry candidates, oriented lexicographically (A < B)."""
        out = []
        present = set(self.symbols)
        for group, members in sorted(self.groups.items()):
            m = sorted(s for s in members if s in present)
            for i in range(len(m)):
                for j in range(i + 1, len(m)):
                    out.append((m[i], m[j], group))
        return out

    def panel(self, a: str, b: str) -> pd.DataFrame:
        """Pair panel on the expected calendar. Missing sessions stay NaN (no forward fill)."""
        cols = ["open", "close", "high", "low", "volume"]
        fa = self.frame[self.frame["symbol"] == a].set_index("date")[cols]
        fb = self.frame[self.frame["symbol"] == b].set_index("date")[cols]
        if fa.empty or fb.empty:
            raise KeyError(f"unknown symbol in pair {a}/{b}")
        start = max(fa.index.min(), fb.index.min())
        end = min(fa.index.max(), fb.index.max())
        cal = self.calendar[(self.calendar >= start) & (self.calendar <= end)]
        p = pd.DataFrame(index=cal)
        p.index.name = "date"
        for c in cols:
            p[f"{c}_a"] = fa[c].reindex(cal)
            p[f"{c}_b"] = fb[c].reindex(cal)
        p["complete"] = p[["open_a", "close_a", "open_b", "close_b"]].notna().all(axis=1)
        return p

    def truncated(self, cutoff: pd.Timestamp) -> "Dataset":
        """Server-side age gate: a copy containing only observations dated <= cutoff."""
        f = self.frame[self.frame["date"] <= cutoff].copy()
        cal = self.calendar[self.calendar <= cutoff]
        return Dataset(f, self.mode, dict(self.manifest) | {"observation_cutoff": cutoff.strftime("%Y-%m-%d")},
                       self.report, self.groups, self.universe_version, cal, "",
                       self.corporate_actions_accounted)  # hash recomputed: gated data has its own cache namespace


def frame_hash(frame: pd.DataFrame) -> str:
    """Content hash of the normalised history (independent of file serialisation)."""
    f = frame.sort_values(["symbol", "date"], kind="mergesort")
    h = hashlib.sha256()
    h.update("|".join(f["symbol"].astype(str)).encode())
    h.update(np.asarray(pd.to_datetime(f["date"]).astype("int64")).tobytes())
    for c in ("open", "high", "low", "close", "volume"):
        h.update(np.round(f[c].to_numpy(dtype=float), 10).tobytes())
    return h.hexdigest()


def normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], format="%Y-%m-%d")
    for c in ("open", "high", "low", "close"):
        out[c] = out[c].astype(float)
    out["volume"] = out["volume"].astype("int64")
    return out.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)


class Provider(abc.ABC):
    name: str = "base"
    mode: str = SYNTHETIC_DEMO

    @abc.abstractmethod
    def symbols(self) -> list[str]: ...

    @abc.abstractmethod
    def history(self, symbol: str) -> pd.DataFrame: ...

    @abc.abstractmethod
    def metadata(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def freshness(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def load_dataset(self) -> Dataset: ...


def build_dataset(frame: pd.DataFrame, mode: str, manifest: dict, groups: dict, universe_version: str,
                  corporate_actions_accounted: bool = False) -> Dataset:
    report = validate_history(frame, mode)
    if not report.ok:
        errs = [i.to_dict() for i in report.issues if i.severity == "error"]
        from ..validation.validate import DataValidationError
        raise DataValidationError(f"dataset failed validation: {errs[:5]}")
    norm = normalise_frame(frame)
    return Dataset(norm, mode, manifest, report, groups, universe_version,
                   corporate_actions_accounted=corporate_actions_accounted)
