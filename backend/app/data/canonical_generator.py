"""Canonical synthetic-data generator, copied unchanged from the build kit (section N).

It is a synthetic test artifact, not actual NSE prices.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd


def generate_demo(destination: str | Path) -> dict:
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    n = 1260
    seed = 20261001
    rng = np.random.Generator(np.random.PCG64(seed))
    noise = rng.standard_normal((n, 24))
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    common1 = np.cumsum(0.0002 + 0.008 * noise[:, 0])
    common2 = np.cumsum(0.0001 + 0.009 * noise[:, 2])
    common4 = np.cumsum(0.0001 + 0.008 * noise[:, 6])
    spread1 = np.zeros(n)
    spread2 = np.zeros(n)
    spread4 = np.zeros(n)
    for t in range(1, n):
        spread1[t] = 0.90 * spread1[t - 1] + 0.006 * noise[t, 1]
        spread2[t] = 0.97 * spread2[t - 1] + 0.007 * noise[t, 3]
        if t < 800:
            spread4[t] = 0.92 * spread4[t - 1] + 0.006 * noise[t, 7]
        else:
            spread4[t] = spread4[t - 1] + 0.0008 + 0.006 * noise[t, 7]
    logs = np.column_stack([
        4.7 + 1.10 * common1 + spread1,
        4.6 + common1,
        5.0 + 0.85 * common2 + spread2,
        4.8 + common2,
        4.9 + np.cumsum(0.0001 + 0.010 * noise[:, 4]),
        5.1 + np.cumsum(0.0001 + 0.010 * noise[:, 5]),
        4.8 + common4 + spread4,
        4.7 + common4,
    ])
    symbols = [
        "S_BANK_A", "S_BANK_B", "S_IT_A", "S_IT_B",
        "S_AUTO_A", "S_AUTO_B", "S_BREAK_A", "S_BREAK_B",
    ]
    rows = []
    for j, symbol in enumerate(symbols):
        closes = np.exp(logs[:, j])
        previous = np.r_[closes[0], closes[:-1]]
        opens = previous * np.exp(0.002 * noise[:, 8 + j])
        ranges = 0.002 + 0.003 * np.abs(noise[:, 16 + j])
        highs = np.maximum(opens, closes) * (1 + ranges)
        lows = np.minimum(opens, closes) / (1 + ranges)
        volumes = (
            1_000_000 * (1 + np.abs(noise[:, 16 + j]))
        ).astype(np.int64)
        for t, date in enumerate(dates):
            rows.append({
                "symbol": symbol,
                "exchange": "SYNTHETIC",
                "series": "DEMO",
                "date": date.strftime("%Y-%m-%d"),
                "open": float(opens[t]),
                "high": float(highs[t]),
                "low": float(lows[t]),
                "close": float(closes[t]),
                "volume": int(volumes[t]),
                "provider": "canonical_synthetic_v1",
                "adjustment_status": "synthetic_no_actions",
                "dataset_id": "pairs_demo_v1_seed_20261001",
            })
    frame = pd.DataFrame(rows).sort_values(
        ["symbol", "date"], kind="mergesort"
    )
    csv_path = out / "canonical_demo.csv"
    frame.to_csv(
        csv_path, index=False, float_format="%.10f", lineterminator="\n"
    )
    manifest = {
        "dataset_id": "pairs_demo_v1_seed_20261001",
        "mode": "SYNTHETIC_DEMO",
        "seed": seed,
        "rng": "PCG64",
        "sessions": n,
        "symbols": symbols,
        "rows": len(frame),
        "start_date": dates[0].strftime("%Y-%m-%d"),
        "end_date": dates[-1].strftime("%Y-%m-%d"),
        "calendar": "weekdays_only_not_nse_calendar",
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "constructed_cases": {
            "S_BANK_A/S_BANK_B": "shared random walk plus stationary spread",
            "S_IT_A/S_IT_B": "shared random walk plus slower stationary spread",
            "S_AUTO_A/S_AUTO_B": "independent random walks",
            "S_BREAK_A/S_BREAK_B": "spread changes regime at observation 800",
        },
    }
    (out / "canonical_demo_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
