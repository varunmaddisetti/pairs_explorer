"""History-schema validation, data-mode labelling and quality reporting.

Policy (build kit section E):
* no forward-filling: missing expected sessions are reported, never hidden;
* unknown adjustment status allows descriptive inspection only;
* synthetic and real data must never be mixed or mislabelled.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HISTORY_COLUMNS = [
    "symbol", "exchange", "series", "date", "open", "high", "low", "close",
    "volume", "provider", "adjustment_status", "dataset_id",
]
ADJUSTMENT_STATUSES = {
    "synthetic_no_actions",      # synthetic: no corporate actions exist by construction
    "raw_unadjusted",            # real raw prices; actions must be handled separately
    "split_bonus_adjusted",      # real prices adjusted for splits/bonuses only
    "total_return_adjusted",     # real prices adjusted for splits/bonuses/dividends
    "unknown",
}
# Adjustment states under which a strategy-return claim may be validated (given other checks).
RETURN_COHERENT_ADJUSTMENTS = {"synthetic_no_actions", "total_return_adjusted", "split_bonus_adjusted"}

SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
REAL_UNVALIDATED = "REAL_UNVALIDATED"
REAL_RESEARCH_VALIDATED = "REAL_RESEARCH_VALIDATED"
DATA_MODES = {SYNTHETIC_DEMO, REAL_UNVALIDATED, REAL_RESEARCH_VALIDATED}

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&_\-]{0,23}$")


class DataValidationError(ValueError):
    """Raised when a dataset must be rejected outright."""


@dataclass
class Issue:
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str
    symbol: str | None = None
    dates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.symbol:
            d["symbol"] = self.symbol
        if self.dates:
            d["dates"] = self.dates[:50]
            d["n_dates"] = len(self.dates)
        return d


@dataclass
class ValidationReport:
    mode: str
    issues: list[Issue]
    symbols: dict[str, dict]
    calendar: str
    expected_sessions: int

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def missing_sessions(self, symbol: str) -> list[str]:
        return self.symbols.get(symbol, {}).get("missing_sessions", [])

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "calendar": self.calendar,
            "expected_sessions": self.expected_sessions,
            "n_errors": sum(i.severity == "error" for i in self.issues),
            "n_warnings": sum(i.severity == "warning" for i in self.issues),
            "issues": [i.to_dict() for i in self.issues],
            "symbols": {
                s: {k: v for k, v in info.items() if k != "missing_sessions"}
                | {"missing_sessions": info.get("missing_sessions", [])[:50]}
                for s, info in self.symbols.items()
            },
        }


def is_synthetic_frame(df: pd.DataFrame) -> pd.Series:
    return (
        (df["exchange"] == "SYNTHETIC")
        | df["provider"].astype(str).str.contains("synthetic", case=False)
        | (df["adjustment_status"] == "synthetic_no_actions")
    )


def check_labelling(df: pd.DataFrame, declared_mode: str) -> None:
    """Reject mixed synthetic/real data and labels that contradict the declared mode."""
    if declared_mode not in DATA_MODES:
        raise DataValidationError(f"unknown data mode {declared_mode!r}")
    syn = is_synthetic_frame(df)
    if syn.any() and (~syn).any():
        raise DataValidationError("dataset mixes synthetic and real-labelled rows; refusing to load")
    if df["dataset_id"].nunique() != 1:
        raise DataValidationError("dataset contains more than one dataset_id")
    if declared_mode == SYNTHETIC_DEMO and not syn.all():
        raise DataValidationError("declared SYNTHETIC_DEMO but rows are not labelled synthetic")
    if declared_mode != SYNTHETIC_DEMO and syn.any():
        raise DataValidationError("declared real-data mode but rows are labelled synthetic")
    bad = set(df["adjustment_status"].unique()) - ADJUSTMENT_STATUSES
    if bad:
        raise DataValidationError(f"unknown adjustment_status values: {sorted(bad)}")


def expected_calendar(df: pd.DataFrame, mode: str) -> tuple[pd.DatetimeIndex, str]:
    dates = pd.to_datetime(df["date"])
    if mode == SYNTHETIC_DEMO:
        return pd.bdate_range(dates.min(), dates.max()), "weekdays_only_not_nse_calendar"
    # Real data: no verified NSE holiday calendar is bundled. Expected sessions are the union of
    # sessions observed for any symbol in the dataset; a date on which *no* symbol traded is
    # treated as an exchange holiday. Documented limitation in METHODOLOGY.md.
    return pd.DatetimeIndex(sorted(dates.unique())), "union_of_observed_sessions"


def validate_history(
    df: pd.DataFrame,
    declared_mode: str,
    min_history: int = 252,
    as_of: pd.Timestamp | None = None,
    stale_business_days: int = 5,
) -> ValidationReport:
    """Validate a common-schema history frame. Raises DataValidationError for fatal problems."""
    missing_cols = [c for c in HISTORY_COLUMNS if c not in df.columns]
    if missing_cols:
        raise DataValidationError(f"missing columns: {missing_cols}")
    if df.empty:
        raise DataValidationError("dataset is empty")
    check_labelling(df, declared_mode)

    issues: list[Issue] = []
    work = df.copy()
    try:
        work["date"] = pd.to_datetime(work["date"], format="%Y-%m-%d")
    except (ValueError, TypeError) as exc:
        raise DataValidationError(f"dates must be ISO YYYY-MM-DD: {exc}") from exc
    for c in ("open", "high", "low", "close", "volume"):
        work[c] = pd.to_numeric(work[c], errors="coerce")

    bad_symbols = sorted({s for s in work["symbol"].astype(str) if not SYMBOL_RE.match(s)})
    if bad_symbols:
        issues.append(Issue("error", "bad_symbol", f"invalid symbol identifiers: {bad_symbols[:10]}"))

    dup = work.duplicated(["symbol", "date"], keep=False)
    if dup.any():
        for sym, g in work[dup].groupby("symbol"):
            issues.append(Issue("error", "duplicate_dates", "duplicate symbol/date rows", sym,
                                sorted(g["date"].dt.strftime("%Y-%m-%d").unique())))

    px = work[["open", "high", "low", "close"]].to_numpy(dtype=float)
    nonpos = ~np.isfinite(px).all(axis=1) | (px <= 0).any(axis=1)
    if nonpos.any():
        for sym, g in work[nonpos].groupby("symbol"):
            issues.append(Issue("error", "nonpositive_or_nonfinite_price",
                                "prices must be positive and finite", sym,
                                list(g["date"].dt.strftime("%Y-%m-%d"))))
    ohlc_bad = (
        (work["high"] < work[["open", "close", "low"]].max(axis=1) * (1 - 1e-12))
        | (work["low"] > work[["open", "close", "high"]].min(axis=1) * (1 + 1e-12))
    ) & ~nonpos
    if ohlc_bad.any():
        for sym, g in work[ohlc_bad].groupby("symbol"):
            issues.append(Issue("error", "inconsistent_ohlc", "high/low do not bound open/close", sym,
                                list(g["date"].dt.strftime("%Y-%m-%d"))))
    vol_bad = ~np.isfinite(work["volume"].to_numpy(dtype=float)) | (work["volume"] < 0)
    if vol_bad.any():
        for sym, g in work[vol_bad].groupby("symbol"):
            issues.append(Issue("error", "bad_volume", "volume must be finite and nonnegative", sym,
                                list(g["date"].dt.strftime("%Y-%m-%d"))))

    for sym, g in work.groupby("symbol", sort=True):
        if not g["date"].is_monotonic_increasing:
            issues.append(Issue("warning", "unsorted", "rows were not in date order (sorted on load)", sym))
        idents = g[["exchange", "series"]].drop_duplicates()
        if len(idents) > 1:
            issues.append(Issue("error", "identity_change",
                                "exchange/series changes within one symbol history; needs identity mapping", sym))

    cal, cal_name = expected_calendar(work, declared_mode)
    symbols: dict[str, dict] = {}
    for sym, g in work.groupby("symbol", sort=True):
        d = pd.DatetimeIndex(g["date"].drop_duplicates().sort_values())
        span = cal[(cal >= d.min()) & (cal <= d.max())]
        missing = span.difference(d)
        off_cal = d.difference(cal)
        adj = sorted(g["adjustment_status"].unique())
        info = {
            "rows": int(len(g)),
            "first_date": d.min().strftime("%Y-%m-%d"),
            "last_date": d.max().strftime("%Y-%m-%d"),
            "missing_sessions": [x.strftime("%Y-%m-%d") for x in missing],
            "n_missing_sessions": int(len(missing)),
            "adjustment_status": adj,
            "exchange": str(g["exchange"].iloc[0]),
            "series": str(g["series"].iloc[0]),
        }
        symbols[sym] = info
        if len(missing):
            issues.append(Issue("warning", "missing_sessions",
                                "expected sessions absent; NOT forward-filled. Folds containing them are "
                                "ineligible for the strict backtest", sym, info["missing_sessions"]))
        if len(off_cal):
            issues.append(Issue("error", "off_calendar_dates", "dates outside the expected calendar "
                                "(e.g. weekend rows in the synthetic weekday calendar)", sym,
                                [x.strftime("%Y-%m-%d") for x in off_cal]))
        if len(d) < min_history:
            issues.append(Issue("warning", "short_history",
                                f"{len(d)} sessions < {min_history} required for one formation window", sym))
        if "unknown" in adj:
            issues.append(Issue("warning", "unknown_adjustment",
                                "adjustment status unknown: descriptive raw-price inspection only; "
                                "validated strategy-return claims are blocked", sym))
        if declared_mode != SYNTHETIC_DEMO and as_of is not None:
            lag = len(pd.bdate_range(d.max(), as_of)) - 1
            if lag > stale_business_days:
                issues.append(Issue("warning", "stale", f"last observation is {lag} business days old", sym))
    if declared_mode == SYNTHETIC_DEMO:
        issues.append(Issue("info", "synthetic_calendar",
                            "weekday simulation calendar; this is not an NSE holiday calendar"))
    return ValidationReport(declared_mode, issues, symbols, cal_name, int(len(cal)))


def assert_strategy_returns_allowed(mode: str, adjustment_statuses: set[str], corporate_actions_accounted: bool) -> None:
    """Gate for *validated* strategy-return claims (build kit section E).

    Raises DataValidationError when only a labelled price-only diagnostic is permissible.
    """
    if mode == SYNTHETIC_DEMO and adjustment_statuses == {"synthetic_no_actions"}:
        return
    if "unknown" in adjustment_statuses:
        raise DataValidationError("unknown adjustment status: validated strategy returns are blocked")
    if mode != REAL_RESEARCH_VALIDATED:
        raise DataValidationError(f"mode {mode} is not research-validated; only a PRICE-ONLY DIAGNOSTIC is allowed")
    if not adjustment_statuses <= RETURN_COHERENT_ADJUSTMENTS or not corporate_actions_accounted:
        raise DataValidationError("prices/corporate actions are not coherent for return accounting")


def finite_or_none(x: float | None) -> float | None:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None
