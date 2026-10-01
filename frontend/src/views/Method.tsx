/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { api, type Status } from "../api";
import { ModeBadge, Panel } from "../components/Common";

export default function Method({ status }: { status: Status }) {
  const [diag, setDiag] = useState<any>(null);
  const [exp, setExp] = useState<any>(null);
  useEffect(() => { api.diagnostics().then(setDiag).catch(() => setDiag(null)); api.experiments().then(setExp).catch(() => setExp(null)); }, []);
  const p = status.defaults;
  return (
    <div className="method">
      <div className="view-head"><div><p className="eyebrow">Method & data</p><h2>How every number is produced</h2></div></div>
      <div className="grid2">
        <Panel title="Dataset status" testId="dataset-status">
          <p><ModeBadge mode={status.mode} large /></p>
          <table className="kv"><tbody>
            {Object.entries(status.statuses).map(([k, v]) => <tr key={k}><th>{k}</th><td data-testid={`status-${k}`}>{v ? "yes" : "no"}</td></tr>)}
            <tr><th>Dataset</th><td>{status.dataset_id}</td></tr>
            <tr><th>Content hash</th><td className="mono">{status.dataset_content_sha256.slice(0, 24)}…</td></tr>
            <tr><th>Price basis</th><td>{String(status.manifest.price_basis)}</td></tr>
            <tr><th>Corporate actions</th><td>{String(status.manifest.corporate_actions)}</td></tr>
            <tr><th>Calendar</th><td>{status.calendar}</td></tr>
            <tr><th>Universe</th><td>{status.universe_version}: {Object.entries(status.groups).map(([g, s]) => `${g} (${s.join(", ")})`).join("; ")}</td></tr>
            <tr><th>Display route</th><td>{status.display_policy.route}; age gate {status.display_policy.require_age_lag ? `${status.display_policy.lag_calendar_days} days → cutoff ${status.display_policy.observation_cutoff}` : "off (local research)"}</td></tr>
          </tbody></table>
          <p className="panel-note">Technical access is not public-display permission. Real NSE data has not been retrieved or validated in this build; see REAL_DATA_READINESS.md.</p>
        </Panel>
        <Panel title="Source diagnostics" testId="source-diagnostics">
          {!diag && <p className="fine">Loading…</p>}
          {diag && <table className="kv"><tbody>
            <tr><th>Active provider</th><td>{diag.active_provider.provider}: {diag.active_provider.status} ({diag.active_provider.rows} rows)</td></tr>
            <tr><th>Validation</th><td>{diag.data_quality.ok ? "passed" : "FAILED"}: {diag.data_quality.n_errors} errors, {diag.data_quality.n_warnings} warnings</td></tr>
            <tr><th>Cache namespace</th><td className="mono">{diag.cache_namespace}</td></tr>
            <tr><th>NSE MCP</th><td>{diag.nse_mcp.recent_refresh_attempts.length
              ? diag.nse_mcp.recent_refresh_attempts.slice(-2).map((x: any, i: number) => <div key={i}>{x.at}: {x.outcome}{x.detail ? ` (${String(x.detail).slice(0, 120)})` : ""}</div>)
              : "no refresh attempted"}<div className="fine">{diag.nse_mcp.status_note}</div></td></tr>
            {exp && <tr><th>Experiments</th><td>{exp.total_runs} runs, {exp.distinct_parameter_versions} parameter versions, {exp.exploratory_runs} exploratory, {exp.runs_touching_holdout} touching the holdout</td></tr>}
          </tbody></table>}
        </Panel>
      </div>

      <Panel title="Spread model" className="prose">
        <p>Pair orientation is fixed by lexicographic symbol order (A first, B second), never by which direction gives the smaller p-value.</p>
        <pre className="eq">{`log(P_A,t) = α + β · log(P_B,t) + ε_t           (OLS, ${p.formation_window} formation sessions)
s_t = log(P_A,t) − α − β · log(P_B,t)
μ = mean(s), σ = sd(s, ddof=1)                  (last ${p.calibration_window} formation residuals)
z_t = (s_t − μ) / σ`}</pre>
        <p><b>z</b> is a distance in historical spread standard deviations. It is not a probability of profit.
          Duplicated, constant, near-identical or rank-deficient inputs are reported as invalid pairs rather than given an impressive p-value.</p>
      </Panel>

      <div className="grid2">
        <Panel title="Inference" className="prose">
          <p>Engle–Granger two-step test (statsmodels <code>coint</code>, constant, AIC lag selection with Schwert maximum lag). Null: <i>no cointegration</i>.
            Every valid predefined same-industry candidate is tested at each formation date and p-values are adjusted with
            Benjamini–Yekutieli (<code>fdr_by</code>) at {p.fdr_alpha}. Raw and adjusted values, family size and skipped tests are shown.</p>
          <p>Eligibility also requires β in [{p.beta_min}, {p.beta_max}] and a half-life in [{p.half_life_min}, {p.half_life_max}] sessions,
            estimated from Δs_t = c + κ s_(t−1) + e_t with ρ = 1 + κ and half-life = −ln 2 / ln ρ only when 0 &lt; ρ &lt; 1.</p>
          <p>ADF (null unit root) and KPSS (null stationarity) diagnostics on each log price help judge the I(1) assumption. Non-rejection does not prove a unit root.</p>
        </Panel>
        <Panel title="Backtest timing and accounting" className="prose">
          <ul>
            <li>Fit on {p.formation_window} sessions, freeze for the next {p.evaluation_block}; refit only at the next fold.</li>
            <li>Signal at close t → fill at open t+1. The last formation close may fill at the first evaluation open.</li>
            <li>Long spread when −{p.entry_z_max} &lt; z ≤ −{p.entry_z}; short spread when {p.entry_z} ≤ z &lt; {p.entry_z_max}.</li>
            <li>Exit priority: invalid data → adverse (±{p.adverse_z}) → max hold ({p.max_holding}) → convergence (±{p.exit_z}, direction-specific) → scheduled fold-boundary close.</li>
            <li>Re-entry no earlier than the second session after an exit (one complete flat session).</li>
            <li>G = {p.gross_exposure} × pre-entry equity; w_A = 1/(1+β), w_B = β/(1+β); quantities frozen until exit.</li>
            <li>Costs: commission {p.commission_bps} + levies {p.levy_bps} bps per fill on traded notional; slippage {p.slippage_bps} bps applied adversely to prices; borrow {p.borrow_annual * 100}% ACT/365 on the previous short market value; cash interest 0%.</li>
            <li>Last {p.final_holdout} sessions are the final holdout, reported separately.</li>
          </ul>
        </Panel>
      </div>

      <Panel title="Limitations" className="prose">
        <ul>
          <li>Synthetic demo: weekday calendar, no holidays, no corporate actions; generator construction labels are not used by any inference.</li>
          <li>Independent pair sleeves only; results are not aggregated into a portfolio.</li>
          <li>Borrow availability, SLB cost, margin and futures equivalents are NOT VERIFIED. Real-world implementability is not claimed.</li>
          <li>The BY correction does not remove every form of repeated-search or model-selection bias; experiment counts are logged.</li>
          <li>No structural-break test is implemented; β-stability warnings are explanatory heuristics.</li>
        </ul>
      </Panel>

      <Panel title="Reproduce" className="prose">
        <pre className="eq">{`make demo      # start locally (synthetic, no keys)
make test      # numerical, accounting, no-lookahead, provider and API tests
make doctor    # tools, versions, config, provider status
python scripts/reproduce_run.py <bundle>/manifest.json`}</pre>
        <p className="fine">Canonical CSV sha256 {String(status.manifest.csv_sha256)} · parameters {status.params_hash}</p>
      </Panel>
    </div>
  );
}
