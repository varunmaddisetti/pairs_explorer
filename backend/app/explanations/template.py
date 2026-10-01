"""Deterministic explanation templates. Numbers come only from computed results; no model text."""
from __future__ import annotations

from ..config import ResearchParams

MODE_SENTENCE = {
    "SYNTHETIC_DEMO": "SYNTHETIC DEMO: every price here is generated; nothing describes a real market.",
    "REAL_UNVALIDATED": "REAL, NOT VALIDATED: source data exists but validation/adjustment checks are incomplete.",
    "REAL_RESEARCH_VALIDATED": "Real data that passed the stated research-scope checks.",
}


def _fmt(x, spec=".3f", none="n/a"):
    return none if x is None else format(x, spec)


def explain(det: dict, p: ResearchParams) -> list[str]:
    s = det["stats"]
    fam = det["family"]
    a, b, t = det["a"], det["b"], det["as_of"]
    out = [MODE_SENTENCE.get(det["source_mode"], det["source_mode"])]
    if s["status"] != "tested":
        out.append(f"As of {t}, {a}/{b} could not be tested: {s['skip_reason']}.")
        return out
    out.append(f"Over the {p.formation_window} sessions to {t}, daily log returns had correlation "
               f"{_fmt(s['return_corr'], '.2f')}. That says the two have moved together; it does not by itself "
               "establish a stable spread.")
    out.append(f"Engle-Granger test (null: no cointegration): p = {_fmt(s['coint_p'])}; Benjamini-Yekutieli "
               f"adjusted across the {fam['family_size']}-pair family: p_adj = {_fmt(s['coint_p_adj'])} "
               f"({'below' if s.get('fdr_reject') else 'not below'} the nominal {p.fdr_alpha}).")
    if s.get("fdr_reject"):
        out.append("The tested spread shows evidence consistent with stationarity under the model's assumptions. "
                   "This is not a probability that it will converge.")
    else:
        out.append("The evidence for a mean-reverting spread is weak in this window; the test did not reject "
                   "'no cointegration' after correction (which does not prove the absence of a relationship).")
    z = s["z_last"]
    out.append(f"Hedge coefficient beta = {s['beta']:.3f}. The latest spread sits {abs(z):.2f} historical standard "
               f"deviations {'above' if z >= 0 else 'below'} its {p.calibration_window}-session calibration mean "
               f"(z = {z:+.2f}). z is a distance, not a probability of profit.")
    if s["half_life"] is not None:
        out.append(f"Estimated half-life: {s['half_life']:.1f} sessions (a historical descriptor, not a deadline).")
    else:
        out.append(f"No half-life is reported: {s['hl_status']}.")
    for w in det["beta_history"]["warnings"]:
        out.append(f"Stability warning: {w}.")
    if s["eligible"]:
        out.append(f"Eligible under the pre-specified screens; ranked descriptively by |z| among eligible pairs.")
    else:
        out.append("Not eligible: " + "; ".join(s["exclusion_reasons"]) + ".")
    return out


def what_changed(prior: dict | None, det: dict, p: ResearchParams) -> list[str]:
    """Directly computed differences versus 21 sessions earlier. No news, no causes."""
    if prior is None:
        return ["No comparison: fewer than 21 earlier sessions are available."]
    a, b = prior["stats"], det["stats"]
    lines = [f"Compared with {prior['as_of']} (21 sessions earlier):"]
    if a["status"] != "tested" or b["status"] != "tested":
        lines.append(f"test status {a['status']} -> {b['status']}")
        return lines
    lines.append(f"z-score {a['z_last']:+.2f} -> {b['z_last']:+.2f} (change {b['z_last'] - a['z_last']:+.2f}).")
    lines.append(f"beta {a['beta']:.3f} -> {b['beta']:.3f}.")
    lines.append(f"raw Engle-Granger p {a['coint_p']:.3f} -> {b['coint_p']:.3f}; "
                 f"adjusted {a['coint_p_adj']:.3f} -> {b['coint_p_adj']:.3f}.")
    if (a["half_life"] is None) != (b["half_life"] is None) or a["half_life"] is not None:
        lines.append(f"half-life {_fmt(a['half_life'], '.1f')} -> {_fmt(b['half_life'], '.1f')} sessions.")
    lines.append(f"return correlation {_fmt(a['return_corr'], '.2f')} -> {_fmt(b['return_corr'], '.2f')}.")
    if a["eligible"] != b["eligible"]:
        lines.append(f"eligibility changed: {'eligible' if a['eligible'] else 'not eligible'} -> "
                     f"{'eligible' if b['eligible'] else 'not eligible'}.")
    return lines
