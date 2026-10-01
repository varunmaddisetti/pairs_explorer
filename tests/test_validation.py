"""Gate J8: data validation and labelling."""
import pandas as pd
import pytest

from app.backtest.run import run_pair_backtest
from app.providers.base import build_dataset
from app.validation.validate import (DataValidationError, assert_strategy_returns_allowed, validate_history)


def real_frame(n=300, syms=("AAA", "BBB")):
    dates = pd.bdate_range("2023-01-02", periods=n)
    rows = []
    for j, s in enumerate(syms):
        for i, d in enumerate(dates):
            c = 100 + j * 10 + (i % 7) * 0.5 + i * 0.01
            rows.append({"symbol": s, "exchange": "NSE", "series": "EQ", "date": d.strftime("%Y-%m-%d"),
                         "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000,
                         "provider": "user_file", "adjustment_status": "total_return_adjusted",
                         "dataset_id": "test_real"})
    return pd.DataFrame(rows)


def codes(rep):
    return {i.code for i in rep.issues}


def test_clean_frame_ok():
    assert validate_history(real_frame(), "REAL_UNVALIDATED").ok


def test_rejects_zero_price():
    f = real_frame(); f.loc[3, "close"] = 0.0
    rep = validate_history(f, "REAL_UNVALIDATED")
    assert not rep.ok and "nonpositive_or_nonfinite_price" in codes(rep)


def test_rejects_duplicate_dates():
    f = pd.concat([real_frame(), real_frame().iloc[[5]]])
    rep = validate_history(f, "REAL_UNVALIDATED")
    assert not rep.ok and "duplicate_dates" in codes(rep)


def test_rejects_impossible_ohlc():
    f = real_frame(); f.loc[7, "high"] = f.loc[7, "close"] * 0.9
    assert "inconsistent_ohlc" in codes(validate_history(f, "REAL_UNVALIDATED"))


def test_negative_volume_and_bad_symbol():
    f = real_frame(); f.loc[2, "volume"] = -1; f.loc[f["symbol"] == "BBB", "symbol"] = "=cmd|x"
    c = codes(validate_history(f, "REAL_UNVALIDATED"))
    assert {"bad_volume", "bad_symbol"} <= c


def test_missing_sessions_reported_not_filled(ds, params):
    f = ds.frame.copy()
    drop_date = ds.calendar[300]
    f = f[~((f["symbol"] == "S_BANK_A") & (f["date"] == drop_date))]
    f["date"] = f["date"].dt.strftime("%Y-%m-%d")
    rep = validate_history(f, "SYNTHETIC_DEMO")
    assert rep.ok and rep.missing_sessions("S_BANK_A") == [drop_date.strftime("%Y-%m-%d")]
    gapped = build_dataset(f, "SYNTHETIC_DEMO", ds.manifest, ds.groups, ds.universe_version, True)
    panel = gapped.panel("S_BANK_A", "S_BANK_B")
    assert pd.isna(panel.loc[drop_date, "close_a"])               # NOT forward-filled
    r = run_pair_backtest(gapped, "S_BANK_A", "S_BANK_B", params)
    fold0 = r["folds"][0]                                          # gap inside the fold-0 evaluation block
    assert not fold0["tradable"]
    assert "missing_sessions_in_evaluation_block(strict)" in fold0["exclusion_reasons"]
    later = [f for f in r["folds"] if f["formation_start"] <= drop_date.strftime("%Y-%m-%d") <= f["formation_end"]]
    assert later and all(any("missing_sessions_in_formation" in x for x in f["exclusion_reasons"]) for f in later)


def test_unknown_adjustment_blocks_validated_returns():
    with pytest.raises(DataValidationError):
        assert_strategy_returns_allowed("REAL_RESEARCH_VALIDATED", {"unknown"}, True)
    with pytest.raises(DataValidationError):
        assert_strategy_returns_allowed("REAL_UNVALIDATED", {"total_return_adjusted"}, True)
    assert_strategy_returns_allowed("SYNTHETIC_DEMO", {"synthetic_no_actions"}, True)
    f = real_frame(); f["adjustment_status"] = "unknown"
    assert "unknown_adjustment" in codes(validate_history(f, "REAL_UNVALIDATED"))


def test_unvalidated_real_backtest_is_labelled_price_only(params):
    f = real_frame(600)
    import numpy as np
    rng = np.random.default_rng(3)
    for s in ("AAA", "BBB"):
        m = f["symbol"] == s
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, m.sum())))
        f.loc[m, "close"] = c; f.loc[m, "open"] = c; f.loc[m, "high"] = c * 1.01; f.loc[m, "low"] = c * 0.99
    ds = build_dataset(f, "REAL_UNVALIDATED", {}, {"G": ["AAA", "BBB"]}, "test")
    r = run_pair_backtest(ds, "AAA", "BBB", params, include_comparators=False)
    assert r["result_label"].startswith("PRICE-ONLY DIAGNOSTIC")


def test_mixed_and_mislabelled_data_rejected(ds):
    syn = ds.frame.head(10).copy(); syn["date"] = syn["date"].dt.strftime("%Y-%m-%d")
    real = real_frame(10); real["dataset_id"] = syn["dataset_id"].iloc[0]
    with pytest.raises(DataValidationError, match="mixes synthetic"):
        validate_history(pd.concat([syn, real]), "SYNTHETIC_DEMO")
    with pytest.raises(DataValidationError, match="labelled synthetic"):
        validate_history(syn, "REAL_UNVALIDATED")
    with pytest.raises(DataValidationError, match="not labelled synthetic"):
        validate_history(real_frame(), "SYNTHETIC_DEMO")
    with pytest.raises(DataValidationError, match="more than one dataset_id"):
        f = real_frame(); f.loc[0, "dataset_id"] = "other"
        validate_history(f, "REAL_UNVALIDATED")


def test_weekend_row_in_synthetic_calendar_rejected(ds):
    f = ds.frame.head(30).copy(); f["date"] = f["date"].dt.strftime("%Y-%m-%d")
    f.loc[f.index[3], "date"] = "2021-02-06"  # a Saturday inside the range
    rep = validate_history(f.drop_duplicates(["symbol", "date"]), "SYNTHETIC_DEMO")
    assert "off_calendar_dates" in codes(rep)
