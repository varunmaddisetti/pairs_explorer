"""Server-side observation-age gate and display-permission policy (build kit section D).

When the active display route requires an age lag, the dataset itself is truncated before any
endpoint sees it, so scanner, pair detail, playback reveals, backtests, exports and cards are all
filtered by the same cutoff. Technical data access never sets public-display permission.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .config import load_display_policy
from .providers.base import Dataset
from .validation.validate import SYNTHETIC_DEMO


class DisplayNotPermitted(PermissionError):
    pass


@dataclass
class DisplayPolicy:
    route: str
    require_age_lag: bool
    lag_calendar_days: int
    public_display_permitted: bool
    reference_date: date

    @classmethod
    def load(cls, route: str | None = None, reference_date: date | None = None) -> "DisplayPolicy":
        cfg = load_display_policy()
        route = route or os.environ.get("PDE_DISPLAY_ROUTE") or cfg.get("active_route", "local_research")
        rcfg = cfg["routes"][route]
        ref = reference_date or (date.fromisoformat(os.environ["PDE_REFERENCE_DATE"])
                                 if os.environ.get("PDE_REFERENCE_DATE") else date.today())
        return cls(route, bool(rcfg.get("require_age_lag", False)), int(rcfg.get("lag_calendar_days", 0)),
                   bool(cfg.get("public_display_permitted", False)), ref)

    @property
    def cutoff(self) -> pd.Timestamp | None:
        if not self.require_age_lag:
            return None
        return pd.Timestamp(self.reference_date - timedelta(days=self.lag_calendar_days))

    def apply(self, ds: Dataset) -> Dataset:
        if self.route != "local_research" and ds.mode != SYNTHETIC_DEMO and not self.public_display_permitted:
            raise DisplayNotPermitted(
                f"real data ({ds.mode}) may not be shown on route '{self.route}': public display permission "
                "has not been established (see DATA_RIGHTS.md)")
        c = self.cutoff
        if c is None or ds.calendar[-1] <= c:
            return ds
        return ds.truncated(c)

    def to_dict(self) -> dict:
        c = self.cutoff
        return {"route": self.route, "require_age_lag": self.require_age_lag,
                "lag_calendar_days": self.lag_calendar_days if self.require_age_lag else None,
                "observation_cutoff": c.strftime("%Y-%m-%d") if c is not None else None,
                "public_display_permitted": self.public_display_permitted,
                "reference_date": self.reference_date.isoformat(),
                "note": "45-day buffer is a conservative product setting, not legal permission; the SEBI "
                        "education-data circular (8 May 2026) states a 30-day lag - verify before launch."}
