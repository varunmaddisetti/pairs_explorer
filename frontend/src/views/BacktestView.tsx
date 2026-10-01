/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useMemo, useState } from "react";
import { api, type Backtest, type Status } from "../api";
import { C, Chart } from "../components/Chart";
import { ErrorBox, Loading, ModeBadge, Panel, Stat } from "../components/Common";
import PairPicker from "../components/PairPicker";
import { f, inr, pct, signed } from "../fmt";

type Set = (p: Record<string, string | null>, replace?: boolean) => void;

const FIELDS: { key: string; label: string; step: number; unit?: string }[] = [
  { key: "entry_z", label: "Entry |z| ≥", step: 0.1 }, { key: "entry_z_max", label: "Entry |z| <", step: 0.1 },
  { key: "exit_z", label: "Exit band", step: 0.1 }, { key: "adverse_z", label: "Adverse |z|", step: 0.1 },
  { key: "max_holding", label: "Max hold", step: 1, unit: "sessions" }, { key: "cooldown_sessions", label: "Cooldown", step: 1, unit: "sessions" },
  { key: "gross_exposure", label: "Gross exposure", step: 0.05, unit: "× equity" },
  { key: "starting_equity", label: "Starting equity", step: 1000, unit: "₹" },
  { key: "commission_bps", label: "Commission", step: 1, unit: "bps/fill" }, { key: "slippage_bps", label: "Slippage", step: 1, unit: "bps/fill" },
  { key: "levy_bps", label: "Other levies", step: 1, unit: "bps/fill" }, { key: "borrow_annual", label: "Borrow", step: 0.005, unit: "annual, ACT/365" },
];

export default function BacktestView({ status, a, b, params, setParams }: {
  status: Status; a: string; b: string; params: URLSearchParams; setParams: Set }) {
  const defaults = status.defaults;
  const overrides = useMemo(() => {
    const o: Record<string, number> = {};
    for (const fl of FIELDS) { const v = params.get(`p_${fl.key}`); if (v !== null && v !== "" && Number.isFinite(Number(v))) o[fl.key] = Number(v); }
    return o;
  }, [params]);
  const strict = params.get("strict") !== "0";
  const [form, setForm] = useState<Record<string, number>>({});
  const [res, setRes] = useState<Backtest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm({ ...Object.fromEntries(FIELDS.map((x) => [x.key, defaults[x.key]])), ...overrides }); }, [overrides, defaults]);

  const run = () => {
    setBusy(true); setErr(null);
    api.backtest({ a, b, strict, params: overrides }).then(setRes).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  useEffect(run, [a, b, strict, overrides]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = () => {
    const patch: Record<string, string | null> = {};
    let same = true;
    for (const fl of FIELDS) {
      const v = form[fl.key] !== defaults[fl.key] ? String(form[fl.key]) : null;
      patch[`p_${fl.key}`] = v;
      if (v !== params.get(`p_${fl.key}`)) same = false;
    }
    if (same) run(); else setParams(patch, true);
  };
  const reset = () => setParams(Object.fromEntries(FIELDS.map((x) => [`p_${x.key}`, null])), true);
  const nonDefault = FIELDS.filter((x) => form[x.key] !== undefined && form[x.key] !== defaults[x.key]);

  return (
    <div className="backtest">
      <div className="view-head">
        <div><p className="eyebrow">Chronological backtest · independent pair sleeve</p><h2>{a} / {b}</h2></div>
        <div className="head-actions">
          <PairPicker status={status} a={a} b={b} onChange={(x, y) => setParams({ a: x, b: y })} />
          {res?.run_id && <a className="button" href={api.bundleUrl(res.run_id)} download data-testid="export-bundle">Export run bundle (.zip)</a>}
        </div>
      </div>

      <Panel title="Assumptions (visible and editable)" testId="assumptions"
        note={<>Fees and borrow are generic scenarios, <b>not</b> verified Indian broker tariffs; borrow availability is NOT VERIFIED. Cash interest
          and risk-free rate are fixed at 0%. Slippage moves execution prices adversely and is never also charged as a fee. Formation
          {" "}{defaults.formation_window}, evaluation block {defaults.evaluation_block}, calibration {defaults.calibration_window} and BY-FDR at
          {" "}{defaults.fdr_alpha} are fixed pre-specified settings.</>}>
        <div className="form-grid">
          {FIELDS.map((fl) => (
            <label key={fl.key} className={form[fl.key] !== defaults[fl.key] ? "changed" : ""}>
              <span>{fl.label}{fl.unit ? <em> {fl.unit}</em> : null}</span>
              <input type="number" step={fl.step} value={form[fl.key] ?? ""} data-testid={`param-${fl.key}`}
                onChange={(e) => setForm({ ...form, [fl.key]: Number(e.target.value) })} />
            </label>
          ))}
          <label className="check"><input type="checkbox" checked={strict} data-testid="strict-toggle"
            onChange={(e) => setParams({ strict: e.target.checked ? null : "0" }, true)} /> Strict data mode (folds with missing sessions are not traded)</label>
        </div>
        <div className="row-actions">
          <button className="primary" onClick={apply} disabled={busy} data-testid="run-backtest">{busy ? "Running…" : "Run backtest"}</button>
          <button onClick={reset}>Reset to defaults</button>
          {nonDefault.length > 0 && <span className="warn inline">Non-default settings make this run exploratory and it is logged as such.</span>}
        </div>
      </Panel>

      {err && <ErrorBox error={err} />}
      {busy && !res && <Loading what="backtest" />}
      {res && <Results res={res} busy={busy} />}
    </div>
  );
}

function SegmentRow({ name, m }: { name: string; m: any }) {
  if (!m) return <tr><th>{name}</th><td colSpan={6} className="fine">not available (insufficient history)</td></tr>;
  return (
    <tr>
      <th>{name}</th><td className="num">{m.sessions}</td><td className="num">{pct(m.net_return)}</td>
      <td className="num">{m.annualized_return == null ? <span className="fine">n/a (&lt;252 sessions)</span> : pct(m.annualized_return)}</td>
      <td className="num">{pct(m.annualized_volatility)}</td><td className="num">{f(m.sharpe)}</td><td className="num">{pct(m.max_drawdown)}</td>
    </tr>
  );
}

function Results({ res, busy }: { res: Backtest; busy: boolean }) {
  const seg = res.metrics.segments;
  const tm = res.metrics.trades;
  const dates = res.daily.map((x: any) => x.date);
  const eq = res.daily.map((x: any) => x.equity);
  const dd = res.daily.map((x: any) => x.drawdown);
  const zf = res.comparators?.zero_friction;
  const lo = res.comparators?.long_only_ab;
  const hs = res.holdout_start;
  const vline = hs ? [{ type: "line", xref: "x", yref: "paper", x0: hs, x1: hs, y0: 0, y1: 1, line: { color: C.ink2, width: 1, dash: "dot" } }] : [];
  const ann = hs ? [{ x: hs, y: 1, xref: "x", yref: "paper", text: "final holdout →", showarrow: false, xanchor: "left", font: { size: 11, color: C.ink2 } }] : [];
  return (
    <div className={busy ? "results stale" : "results"} data-testid="backtest-results">
      <div className={`result-label ${res.result_label.startsWith("PRICE-ONLY") ? "warn-bg" : ""}`} data-testid="result-label">
        <ModeBadge mode={res.manifest.source_mode} /> <b>{res.result_label}</b> · {res.experiment_class} · run {res.run_id}
      </div>
      {(res.status.insolvent || res.status.halted) && (
        <div className="error" data-testid="halt-state">RUN HALTED: {res.status.halt_reason}. Outstanding exposure: {JSON.stringify(res.status.unresolved_exposure)}</div>
      )}
      <div className="stats-row">
        <Stat label="Net return (all evaluation)" value={pct(seg.all_evaluation.net_return)} testId="bt-net" />
        <Stat label="Zero-friction return" value={pct(zf?.metrics.all_evaluation.net_return)} hint="same signals, no costs" />
        <Stat label="Cash comparator" value={pct(0)} hint="0% interest" />
        <Stat label="Trades" value={tm.trade_count} hint={tm.avg_holding_sessions ? `avg hold ${f(tm.avg_holding_sessions, 1)} sessions` : ""} testId="bt-trades" />
        <Stat label="Total costs" value={inr(res.metrics.costs.total)} hint={`fees ${inr(res.metrics.costs.fees)} · slippage ${inr(res.metrics.costs.slippage_cost_in_prices)} · borrow ${inr(res.metrics.costs.borrow)}`} />
        <Stat label="Win rate · profit factor" value={<>{pct(tm.win_rate, 0)} · {f(tm.profit_factor)}</>} hint={tm.ratio_note ?? `turnover ${f(tm.turnover, 1)}×`} />
      </div>

      <Panel title="Equity: strategy vs comparators (₹, one axis)" testId="equity-chart"
        note={<>Long-only comparison: {lo?.description}. One pair sleeve is not a diversified fund. Gross (zero-friction) and net shown together.</>}>
        <Chart ariaLabel="equity curves" height={320} data={([
          { x: dates, y: eq, type: "scatter", mode: "lines", name: "Strategy (net)", line: { color: C.a, width: 2 } },
          ...(zf ? [{ x: dates, y: zf.equity, type: "scatter" as const, mode: "lines" as const, name: "Zero friction", line: { color: C.a, width: 1.5, dash: "dot" } }] : []),
          ...(lo ? [{ x: lo.dates, y: lo.equity, type: "scatter" as const, mode: "lines" as const, name: "Long-only A+B", line: { color: C.b, width: 1.5 } }] : []),
          { x: [dates[0], dates[dates.length - 1]], y: [res.assumptions.starting_equity, res.assumptions.starting_equity], type: "scatter", mode: "lines", name: "Cash (0%)", line: { color: C.muted, width: 1 } },
        ]) as any[]} layout={{ shapes: vline as any, annotations: ann as any, yaxis: { tickprefix: "₹" } }} />
      </Panel>

      <div className="grid2">
        <Panel title="Drawdown (strategy, net)">
          <Chart ariaLabel="drawdown" height={200} data={[{ x: dates, y: dd, type: "scatter", mode: "lines", fill: "tozeroy",
            line: { color: C.a, width: 1 }, fillcolor: "rgba(42,120,214,0.15)", name: "drawdown" }]}
            layout={{ showlegend: false, yaxis: { tickformat: ".1%" }, shapes: vline as any }} />
        </Panel>
        <Panel title="Results by period" note="Development folds and the final holdout are reported separately; holdout results never feed back into settings.">
          <div className="table-wrap">
            <table className="data compact" data-testid="segments">
              <thead><tr><th>Period</th><th className="num">Sessions</th><th className="num">Net</th><th className="num">Annualized</th><th className="num">Vol</th><th className="num">Sharpe</th><th className="num">Max DD</th></tr></thead>
              <tbody>
                <SegmentRow name="Development" m={seg.development} />
                <SegmentRow name="Final holdout" m={seg.final_holdout} />
                <SegmentRow name="All evaluation" m={seg.all_evaluation} />
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel title="Chronological folds" testId="folds"
        note="Grey: 252-session formation (fit, test, freeze). Coloured: 63-session evaluation with frozen parameters; blue = traded, light = not eligible. Darker outline = final holdout.">
        <FoldDiagram folds={res.folds} />
        <details className="more"><summary>Fold table ({res.folds.length} folds)</summary>
          <div className="table-wrap">
            <table className="data compact">
              <thead><tr><th>#</th><th>Segment</th><th>Formation</th><th>Evaluation</th><th className="num">β</th><th className="num">p</th><th className="num">BY p</th><th className="num">HL</th><th>Traded / reasons</th></tr></thead>
              <tbody>{res.folds.map((x: any) => (
                <tr key={x.k}><td>{x.k}</td><td>{x.segment}</td><td>{x.formation_start} → {x.formation_end}</td><td>{x.evaluation_start} → {x.evaluation_end}</td>
                  <td className="num">{f(x.beta, 3)}</td><td className="num">{f(x.coint_p, 3)}</td><td className="num">{f(x.coint_p_adj, 3)}</td><td className="num">{f(x.half_life, 1)}</td>
                  <td className="reasons">{x.tradable ? "eligible" : x.exclusion_reasons.join("; ")}</td></tr>))}</tbody>
            </table>
          </div>
        </details>
      </Panel>

      <Panel title="Cost stress scenarios" testId="stress" note="Sensitivity scenarios: total friction per leg per fill split as slippage ½, commission ¼, levy ¼; borrow held at the configured rate. Not broker quotes.">
        <div className="table-wrap">
          <table className="data compact">
            <thead><tr><th className="num">bps / leg / fill</th><th>Split</th><th className="num">Borrow</th><th className="num">Net return</th><th className="num">Trades</th><th className="num">Total cost</th></tr></thead>
            <tbody>{(res.stress ?? []).map((s: any) => (
              <tr key={s.friction_bps_per_leg_per_fill}><td className="num">{s.friction_bps_per_leg_per_fill}</td><td>{s.split}</td><td className="num">{pct(s.borrow_annual, 1)}</td>
                <td className="num">{pct(s.net_return)}</td><td className="num">{s.trade_count}</td><td className="num">{inr(s.total_cost)}</td></tr>))}</tbody>
          </table>
        </div>
      </Panel>

      <Panel title={`Trades (${res.trades.length})`} testId="trades">
        {res.trades.length === 0 ? <p className="empty">No trades: no fold had an eligible relationship with an entry signal. That is a valid outcome.</p> : (
          <div className="table-wrap">
            <table className="data compact">
              <thead><tr><th>Fold</th><th>Side</th><th>Signal (close)</th><th className="num">z</th><th>Entry (open)</th><th>Exit</th><th>Reason</th><th className="num">Held</th><th className="num">Gross</th><th className="num">Costs</th><th className="num">Net</th></tr></thead>
              <tbody>{res.trades.map((t: any, i: number) => (
                <tr key={i}><td>{t.fold}</td><td>{t.side.replace("_", " ")}</td><td>{t.signal_date}</td><td className="num">{signed(t.signal_z)}</td><td>{t.entry_date}</td>
                  <td>{t.exit_date} <span className="fine">{t.exit_time}</span></td><td>{t.exit_reason.replace("_", " ")}</td><td className="num">{t.holding_sessions}</td>
                  <td className="num">{inr(t.gross_pnl)}</td><td className="num">{inr(t.fees + t.slippage_cost + t.borrow_cost)}</td><td className="num">{inr(t.net_pnl)}</td></tr>))}</tbody>
            </table>
          </div>)}
        <details className="more"><summary>Fill ledger ({res.fills.length} fills, cash and equity after each fill)</summary>
          <div className="table-wrap">
            <table className="data compact" data-testid="fill-ledger">
              <thead><tr><th>Date</th><th>Time</th><th>Symbol</th><th className="num">Qty</th><th className="num">Ref.</th><th className="num">Exec.</th><th className="num">Notional</th><th className="num">Fee</th><th className="num">Cash after</th><th className="num">Equity after</th><th>Reason</th></tr></thead>
              <tbody>{res.fills.map((x: any, i: number) => (
                <tr key={i}><td>{x.date}</td><td>{x.time}</td><td>{x.symbol}</td><td className="num">{f(x.qty, 3)}</td><td className="num">{f(x.ref_price, 3)}</td><td className="num">{f(x.exec_price, 3)}</td>
                  <td className="num">{inr(x.notional)}</td><td className="num">{inr(x.fee, 2)}</td><td className="num">{inr(x.cash_after, 2)}</td><td className="num">{inr(x.equity_after, 2)}</td><td>{x.reason}</td></tr>))}</tbody>
            </table>
          </div>
        </details>
        <p className="panel-note">Signals are observed at a close and filled at the next open; thresholds are not stop-loss fill prices and gaps can make losses larger.
          Quantities are frozen until exit; fractional shares are a research simplification. Notional weights 1/(1+β) and β/(1+β) are not dollar- or market-neutral unless β = 1.</p>
      </Panel>
      <p className="fine">Result hash (timestamps stripped): {res.result_sha256} · params {res.manifest.params_sha256_16} · dataset {String(res.manifest.dataset_content_sha256).slice(0, 16)} · runs logged: {res.registry.total_runs} (exploratory {res.registry.exploratory_runs})</p>
    </div>
  );
}

function FoldDiagram({ folds }: { folds: any[] }) {
  if (!folds.length) return null;
  const t0 = Date.parse(folds[0].formation_start);
  const t1 = Date.parse(folds[folds.length - 1].evaluation_end);
  const pos = (d: string) => ((Date.parse(d) - t0) / (t1 - t0)) * 100;
  return (
    <div className="folds" role="img" aria-label="fold timeline">
      {folds.map((x) => (
        <div className="fold-row" key={x.k} title={`Fold ${x.k}: ${x.tradable ? "eligible" : x.exclusion_reasons.join("; ")}`}>
          <span className="fold-k">{x.k}</span>
          <div className="fold-track">
            <div className="fold-form" style={{ left: `${pos(x.formation_start)}%`, width: `${pos(x.formation_end) - pos(x.formation_start)}%` }} />
            <div className={`fold-eval ${x.tradable ? "on" : "off"} ${x.segment === "holdout" ? "holdout" : ""}`}
              style={{ left: `${pos(x.evaluation_start)}%`, width: `${Math.max(0.6, pos(x.evaluation_end) - pos(x.evaluation_start))}%` }} />
          </div>
        </div>
      ))}
      <div className="fold-axis"><span>{folds[0].formation_start}</span><span>{folds[folds.length - 1].evaluation_end}</span></div>
    </div>
  );
}
