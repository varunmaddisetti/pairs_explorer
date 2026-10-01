import { useEffect, useMemo, useState } from "react";
import { api, type Curated, type PairRow, type Scanner, type Status } from "../api";
import { ErrorBox, Loading, Panel } from "../components/Common";
import { f, pval, signed } from "../fmt";

type Set = (p: Record<string, string | null>) => void;

export default function Explore({ status, setParams }: { status: Status; setParams: Set }) {
  const [scan, setScan] = useState<Scanner | null>(null);
  const [cur, setCur] = useState<Curated | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"eligible" | "excluded">("eligible");
  const [query, setQuery] = useState("");
  useEffect(() => { api.scanner().then(setScan).catch((e) => setErr(e.message)); }, []);
  useEffect(() => { api.curated().then(setCur).catch(() => setCur(null)); }, []);

  const rows = useMemo(() => {
    const list = scan ? (tab === "eligible" ? scan.eligible : scan.excluded) : [];
    const qq = query.trim().toUpperCase();
    return qq ? list.filter((r) => r.pair.includes(qq) || r.group.toUpperCase().includes(qq)) : list;
  }, [scan, tab, query]);

  const open = (r: { a: string; b: string }, view = "pair", asof?: string) =>
    setParams({ view, a: r.a, b: r.b, asof: asof ?? null, reveal: null });

  return (
    <div className="explore">
      <section className="hero">
        <div>
          <p className="eyebrow">Indian-equity pairs research · transparent and reproducible</p>
          <h1>How far apart have two stocks drifted, and should you believe the spread?</h1>
          <p className="lede">
            See how two stocks moved together, how far their estimated relationship has diverged, whether the evidence is
            consistent with mean reversion after multiple-testing correction, and what a pre-specified hypothetical
            long/short rule would have done in strictly chronological evaluation after explicit costs.
          </p>
        </div>
        <ol className="hero-steps">
          <li><b>Moved together?</b> Normalized prices and return correlation: descriptive only.</li>
          <li><b>Diverged how far?</b> z-score: distance in historical spread standard deviations.</li>
          <li><b>Real evidence?</b> Engle–Granger, Benjamini–Yekutieli adjusted across the family.</li>
          <li><b>What would a rule have done?</b> Walk-forward folds, next-open fills, audited ledger.</li>
          <li><b>What can't the data support?</b> Exclusions, gaps and labels shown, not hidden.</li>
        </ol>
      </section>

      <div className="curated">
        {cur?.teaching && (
          <article className="example good" data-testid="example-teaching">
            <p className="eyebrow">Teaching example · reverted</p>
            <h3>{cur.teaching.a} / {cur.teaching.b}</h3>
            <p>{cur.teaching.summary}</p>
            <div className="row-actions">
              <button className="primary" onClick={() => open(cur.teaching!, "playback", cur.teaching!.as_of)}>Replay as of {cur.teaching.as_of}</button>
              <button onClick={() => open(cur.teaching!)}>Latest detail</button>
            </div>
          </article>
        )}
        {cur?.contrast && (
          <article className="example bad" data-testid="example-contrast">
            <p className="eyebrow">Contrast example · failed reversion</p>
            <h3>{cur.contrast.a} / {cur.contrast.b}</h3>
            <p>{cur.contrast.summary}</p>
            <div className="row-actions">
              <button className="primary" onClick={() => open(cur.contrast!, "playback", cur.contrast!.as_of)}>Replay as of {cur.contrast.as_of}</button>
              <button onClick={() => open(cur.contrast!)}>Latest detail</button>
            </div>
          </article>
        )}
        {!cur && <div className="example muted"><Loading what="curated examples (first run computes them, ~15 s)" /></div>}
        {cur && <p className="fine curated-note">{cur.note}</p>}
      </div>

      <Panel title={<>Scanner {scan && <span className="sub">as of {scan.as_of}</span>}</>} testId="scanner"
        note={scan && <>{scan.family.method}. Family: {scan.family.family_size} tested, {scan.family.n_skipped} skipped,
          {" "}{scan.family.n_eligible} eligible. Ranking is {scan.ranking}; it is not a recommendation or a profitability
          forecast. Universe {status.universe_version}.</>}>
        {err && <ErrorBox error={err} />}
        {!scan && !err && <Loading what="scanner" />}
        {scan && (
          <>
            <div className="toolbar">
              <div className="tabs" role="tablist">
                <button role="tab" aria-selected={tab === "eligible"} className={tab === "eligible" ? "active" : ""}
                  onClick={() => setTab("eligible")} data-testid="tab-eligible">Eligible ({scan.eligible.length})</button>
                <button role="tab" aria-selected={tab === "excluded"} className={tab === "excluded" ? "active" : ""}
                  onClick={() => setTab("excluded")} data-testid="tab-excluded">Excluded ({scan.excluded.length})</button>
              </div>
              <input type="search" placeholder="Search symbol or group" value={query} aria-label="Search pairs"
                onChange={(e) => setQuery(e.target.value)} data-testid="scanner-search" />
            </div>
            {tab === "eligible" && scan.eligible.length === 0 && (
              <div className="empty" data-testid="no-results">
                No pair passes the pre-specified screens as of {scan.as_of}. That is a legitimate result: thresholds are
                not relaxed and correction is not disabled to produce candidates. Inspect the excluded tab for reasons.
              </div>
            )}
            {rows.length > 0 && <ScannerTable rows={rows} excluded={tab === "excluded"} onOpen={(r) => open(r)} />}
          </>
        )}
      </Panel>
    </div>
  );
}

function ScannerTable({ rows, excluded, onOpen }: { rows: PairRow[]; excluded: boolean; onOpen: (r: PairRow) => void }) {
  return (
    <div className="table-wrap">
      <table className="data" data-testid="scanner-table">
        <thead>
          <tr>
            <th>Pair</th><th className="num">z</th><th className="num">Return corr.</th><th className="num">Beta</th>
            <th className="num">EG p (raw)</th><th className="num">BY adj. p</th><th className="num">Half-life</th>
            <th className="num">n</th><th>Last obs.</th><th>Relationship evidence</th>
            {excluded && <th>Exclusion reasons</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.pair} onClick={() => onOpen(r)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(r)}
              data-testid={`row-${r.pair}`}>
              <td><b>{r.pair}</b><div className="fine">{r.group}</div></td>
              <td className="num">{signed(r.z_last)}</td>
              <td className="num">{f(r.return_corr)}</td>
              <td className="num">{f(r.beta, 3)}</td>
              <td className="num">{pval(r.coint_p)}</td>
              <td className="num">{pval(r.coint_p_adj)}</td>
              <td className="num">{r.half_life != null ? f(r.half_life, 1) : r.hl_status ?? "n/a"}</td>
              <td className="num">{r.n_obs}</td>
              <td>{r.last_observation}</td>
              <td>{r.labels?.relationship_evidence}</td>
              {excluded && <td className="reasons">{r.exclusion_reasons.join("; ")}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
