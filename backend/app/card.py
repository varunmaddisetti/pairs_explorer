"""Server-side PNG research card. Rendered from the (already age-gated) dataset only."""
from __future__ import annotations

import io
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter  # noqa: E402
import pandas as pd  # noqa: E402

INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e6e5e0"
SURFACE = "#fcfcfb"
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
BADGE = {"SYNTHETIC_DEMO": ("SYNTHETIC DEMO - generated prices, not market data", "#7a2e0e", "#fde9dc"),
         "REAL_UNVALIDATED": ("REAL DATA - NOT VALIDATED", "#7a5a00", "#fff2cc"),
         "REAL_RESEARCH_VALIDATED": ("REAL DATA - research-validated scope", "#0b4f2a", "#dff3e6")}


def render_card(det: dict) -> bytes:
    s = det["stats"]
    fig = plt.figure(figsize=(12, 6.75), dpi=100, facecolor=SURFACE)
    fig.text(0.04, 0.92, f"{det['a']}  /  {det['b']}", fontsize=26, fontweight="bold", color=INK)
    fig.text(0.04, 0.875, f"Pairs Divergence Explorer  |  as of {det['as_of']}  |  group {det['group']}",
             fontsize=12, color=INK2)
    label, fg, bg = BADGE.get(det["source_mode"], (det["source_mode"], INK, "#eeeeee"))
    fig.text(0.96, 0.925, f"  {label}  ", fontsize=13, fontweight="bold", color=fg, ha="right",
             bbox={"boxstyle": "round,pad=0.5", "fc": bg, "ec": fg, "lw": 1.5})

    ax = fig.add_axes([0.06, 0.2, 0.53, 0.6], facecolor=SURFACE)
    if det.get("formation"):
        f = det["formation"]
        d = pd.to_datetime(f["dates"])
        b = f["bands"]
        for y, ls in [(b["entry"], "--"), (-b["entry"], "--"), (b["adverse"], ":"), (-b["adverse"], ":"),
                      (b["exit"], (0, (1, 3))), (-b["exit"], (0, (1, 3)))]:
            ax.axhline(y, color=MUTED, lw=1, ls=ls)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.axvspan(pd.Timestamp(f["calibration_start"]), d[-1], color="#f0efec", zorder=0)
        ax.plot(d, f["z"], color=SERIES_1, lw=2)
        ax.scatter([d[-1]], [f["z"][-1]], s=60, color=SERIES_1, edgecolor=SURFACE, linewidth=2, zorder=5)
        ax.annotate(f"z = {f['z'][-1]:+.2f}", (d[-1], f["z"][-1]), xytext=(-10, 12), textcoords="offset points",
                    ha="right", fontsize=12, color=INK, fontweight="bold")
        loc = AutoDateLocator()
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(ConciseDateFormatter(loc))
        ax.set_title("Spread z-score over the formation window (shaded: 60-session calibration)",
                     fontsize=11, color=INK2, loc="left")
        tr = ax.get_yaxis_transform()
        for y, name in [(b["entry"], "entry"), (b["adverse"], "adverse"), (b["exit"], "exit")]:
            ax.text(1.01, y, f"{name} +/-{y:g}", transform=tr, va="center", fontsize=9, color=INK2)
    else:
        ax.text(0.5, 0.5, f"Not tested: {s.get('skip_reason')}", ha="center", transform=ax.transAxes, color=INK2)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)

    def fmt(x, spec):
        return "n/a" if x is None else format(x, spec)

    rows = [("Divergence (z)", fmt(s.get("z_last"), "+.2f")),
            ("Hedge beta", fmt(s.get("beta"), ".3f")),
            ("Engle-Granger p (raw)", fmt(s.get("coint_p"), ".3f")),
            (f"BY-adjusted p (family {det['family']['family_size']})", fmt(s.get("coint_p_adj"), ".3f")),
            ("Half-life (sessions)", fmt(s.get("half_life"), ".1f")),
            ("Return correlation", fmt(s.get("return_corr"), ".2f")),
            ("Eligible", "yes" if s.get("eligible") else "no")]
    y = 0.78
    for k, v in rows:
        fig.text(0.68, y, k, fontsize=12, color=INK2)
        fig.text(0.96, y, v, fontsize=13, color=INK, ha="right", fontweight="bold")
        y -= 0.065
    labels = det["labels"]
    fig.text(0.68, y - 0.01, textwrap.fill(f"Relationship: {labels['relationship_evidence']}", 48), fontsize=9,
             color=INK2, va="top")
    caveat = ("Historical, hypothetical research view. z measures distance in historical spread standard deviations, "
              "not a probability of profit. Not investment advice; no recommendation to buy or sell.")
    if det["source_mode"] == "SYNTHETIC_DEMO":
        caveat = "SYNTHETIC DEMO: all prices are generated; no market finding is asserted. " + caveat
    fig.text(0.04, 0.045, textwrap.fill(caveat, 150), fontsize=10, color=INK2)
    fig.text(0.04, 0.012, f"dataset {det['dataset_id']}  |  data through {det['as_of']}", fontsize=8, color=MUTED)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()
