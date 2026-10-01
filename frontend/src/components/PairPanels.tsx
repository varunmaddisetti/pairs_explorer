import type { PairDetail } from "../api";
import { f, pval, signed } from "../fmt";
import { bandShapes, C, Chart } from "./Chart";
import { LabelChips, Panel, Stat } from "./Common";

export function KeyStats({ d }: { d: PairDetail }) {
  const s = d.stats;
  return (
    <div className="stats-row" data-testid="key-stats">
      <Stat label="Divergence z" value={signed(s.z_last)} hint="historical spread SDs" testId="stat-z" />
      <Stat label="Hedge beta" value={f(s.beta, 3)} hint="log-price OLS" />
      <Stat label="EG p · BY adj. p" value={<>{pval(s.coint_p)} · {pval(s.coint_p_adj)}</>} hint={`family of ${d.family.family_size}`} />
      <Stat label="Half-life" value={s.half_life != null ? `${f(s.half_life, 1)} d` : "n/a"} hint={s.hl_status ?? ""} />
      <Stat label="Return corr." value={f(s.return_corr)} hint="formation window" />
      <Stat label="Eligible" value={s.status !== "tested" ? "not tested" : s.eligible ? "yes" : "no"}
        hint={s.eligible ? "pre-specified screens" : (s.exclusion_reasons[0] ?? "")} testId="stat-eligible" />
    </div>
  );
}

export function Explanation({ d }: { d: PairDetail }) {
  return (
    <Panel title="What the numbers say" testId="explanation" className="explain"
      note="Deterministic template filled with backend-computed values; no model-generated text.">
      <ul className="explain-list">{d.explanation.map((x, i) => <li key={i}>{x}</li>)}</ul>
      <LabelChips labels={d.labels} />
    </Panel>
  );
}

export function WhatChanged({ d }: { d: PairDetail }) {
  return (
    <Panel title="What changed?" testId="what-changed" note="Directly computed differences; no news or causes are inferred.">
      <ul className="explain-list compact">{d.what_changed.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </Panel>
  );
}

export function ZChart({ d, testId = "z-chart" }: { d: PairDetail; testId?: string }) {
  if (!d.formation) return <Panel title="Spread z-score"><p className="empty">Not tested: {d.stats.skip_reason}</p></Panel>;
  const fm = d.formation;
  return (
    <Panel title="Spread z-score (formation window, as-of parameters)" testId={testId}
      note={`Shaded: ${fm.dates.length - fm.dates.indexOf(fm.calibration_start)}-session calibration window for μ and σ. Bands: entry ±${fm.bands.entry}, exit ±${fm.bands.exit}, adverse ±${fm.bands.adverse}. In-sample to the fitted window.`}>
      <Chart ariaLabel="z-score over formation window" data={[{ x: fm.dates, y: fm.z, type: "scatter", mode: "lines",
        name: "z", line: { color: C.a, width: 2 }, hovertemplate: "z %{y:.2f}<extra></extra>" }]}
        layout={{ showlegend: false, shapes: [...bandShapes(fm.bands), { type: "rect", xref: "x", yref: "paper",
          x0: fm.calibration_start, x1: fm.dates[fm.dates.length - 1], y0: 0, y1: 1, fillcolor: C.band, line: { width: 0 },
          layer: "below" }], yaxis: { title: { text: "z" } } }} />
    </Panel>
  );
}

export function PriceChart({ d }: { d: PairDetail }) {
  const x = d.descriptive.dates;
  return (
    <Panel title="Normalized prices (start = 100)" testId="price-chart" note={d.descriptive.note}>
      <Chart ariaLabel="normalized prices" data={[
        { x, y: d.descriptive.norm_a, type: "scatter", mode: "lines", name: d.a, line: { color: C.a, width: 2 } },
        { x, y: d.descriptive.norm_b, type: "scatter", mode: "lines", name: d.b, line: { color: C.b, width: 2 } },
      ]} layout={{ yaxis: { title: { text: "index" } } }} />
      {d.descriptive.gaps.length > 0 && <p className="warn">Gaps (not filled): {d.descriptive.gaps.slice(0, 8).join(", ")}</p>}
    </Panel>
  );
}

export function CorrChart({ d }: { d: PairDetail }) {
  return (
    <Panel title="Rolling 63-session return correlation" note={`Whole history to as-of: ${f(d.descriptive.full_period_return_corr)}. Correlation of returns is not cointegration of levels.`}>
      <Chart ariaLabel="rolling correlation" height={220} data={[{ x: d.descriptive.dates, y: d.descriptive.rolling_corr,
        type: "scatter", mode: "lines", name: "corr", line: { color: C.violet, width: 2 } }]}
        layout={{ showlegend: false, yaxis: { range: [-1, 1], title: { text: "ρ" } } }} />
    </Panel>
  );
}

export function SpreadChart({ d }: { d: PairDetail }) {
  if (!d.formation) return null;
  return (
    <Panel title="Log spread  s = log A − α − β log B" note={`α = ${f(d.stats.alpha, 4)}, β = ${f(d.stats.beta, 4)}, μ = ${f(d.stats.mu, 4)}, σ = ${f(d.stats.sigma, 4)}`}>
      <Chart ariaLabel="log spread" height={220} data={[{ x: d.formation.dates, y: d.formation.spread, type: "scatter",
        mode: "lines", name: "spread", line: { color: C.ink2, width: 2 } }]} layout={{ showlegend: false }} />
    </Panel>
  );
}

export function WalkForward({ d }: { d: PairDetail }) {
  if (!d.walk_forward.dates.length) return null;
  return (
    <Panel title="Point-in-time z (walk-forward)" note="Each 63-session block uses parameters frozen at the end of its own formation window: what a viewer could have seen at the time. Breaks at fold boundaries are expected.">
      <Chart ariaLabel="walk-forward z" height={220} data={[{ x: d.walk_forward.dates, y: d.walk_forward.z, type: "scatter",
        mode: "lines", name: "z (OOS)", line: { color: C.a, width: 1.5 } }]}
        layout={{ showlegend: false, shapes: bandShapes({ entry: 2, exit: 0.5, adverse: 3.5 }) }} />
    </Panel>
  );
}

export function MoreDescriptive({ d }: { d: PairDetail }) {
  const x = d.descriptive.dates;
  return (
    <details className="more">
      <summary>More descriptive views: price ratio and drawdowns</summary>
      <div className="grid2">
        <Panel title={`Price ratio ${d.a} / ${d.b}`}>
          <Chart ariaLabel="price ratio" height={200} data={[{ x, y: d.descriptive.ratio, type: "scatter", mode: "lines",
            line: { color: C.ink2, width: 1.5 }, name: "ratio" }]} layout={{ showlegend: false }} />
        </Panel>
        <Panel title="Drawdown from running peak">
          <Chart ariaLabel="drawdowns" height={200} data={[
            { x, y: d.descriptive.drawdown_a, type: "scatter", mode: "lines", name: d.a, line: { color: C.a, width: 1.5 } },
            { x, y: d.descriptive.drawdown_b, type: "scatter", mode: "lines", name: d.b, line: { color: C.b, width: 1.5 } },
          ]} layout={{ yaxis: { tickformat: ".0%" } }} />
        </Panel>
      </div>
    </details>
  );
}

export function Diagnostics({ d }: { d: PairDetail }) {
  const s = d.stats;
  const ur = s.unit_root ?? [];
  const bh = d.beta_history;
  return (
    <Panel title="Diagnostics" testId="diagnostics">
      <div className="grid2">
        <table className="kv">
          <tbody>
            <tr><th>Test</th><td>Engle–Granger (null: no cointegration), constant, AIC lag selection, max lag {s.coint_maxlag ?? "n/a"}</td></tr>
            <tr><th>Statistic</th><td>{f(s.coint_stat, 3)} (crit. 1% {f(s.coint_crit_1pct, 2)}, 5% {f(s.coint_crit_5pct, 2)}, 10% {f(s.coint_crit_10pct, 2)})</td></tr>
            <tr><th>p raw / BY-adjusted</th><td>{pval(s.coint_p)} / {pval(s.coint_p_adj)} across {d.family.family_size} tested ({d.family.n_skipped} skipped)</td></tr>
            <tr><th>Sample</th><td>{s.n_obs} sessions {s.formation_start} → {s.formation_end}</td></tr>
            <tr><th>AR(1) on spread</th><td>ρ = {f(s.rho, 4)}, status {s.hl_status}</td></tr>
            {ur.map((u, i) => (
              <tr key={i}><th>{u.series}</th><td>ADF p {pval(u.adf_pvalue)} (null unit root) · KPSS p {pval(u.kpss_pvalue)}{u.kpss_pvalue_bounded ? " (table-bounded)" : ""} (null stationary)</td></tr>
            ))}
          </tbody>
        </table>
        <div>
          <Chart ariaLabel="beta history" height={200} data={[{ x: bh.history.map((h) => h.formation_end),
            y: bh.history.map((h) => h.beta), type: "scatter", mode: "lines+markers", name: "β",
            marker: { size: 8, color: bh.history.map((h) => (h.eligible ? C.a : C.muted)) }, line: { color: C.a, width: 1.5 } }]}
            layout={{ showlegend: false, title: { text: "β by prior formation window (filled = eligible)", font: { size: 12 } }, margin: { l: 44, r: 10, t: 30, b: 30 } }} />
          {bh.warnings.map((w) => <p className="warn" key={w}>Stability warning: {w}</p>)}
          <p className="fine">{bh.rule}</p>
        </div>
      </div>
      <p className="panel-note">The Engle–Granger method assumes I(1) inputs. Failing to reject a unit root does not prove one;
        BY adjustment is a nominal procedure under assumptions, not a probability that the spread will converge.</p>
    </Panel>
  );
}
