import { useEffect, useMemo, useState } from "react";
import { api, type PairDetail, type Reveal, type Scanner, type Status } from "../api";
import { bandShapes, C, Chart } from "../components/Chart";
import { ErrorBox, Loading, ModeBadge, Panel } from "../components/Common";
import { Explanation, KeyStats, WhatChanged, ZChart } from "../components/PairPanels";
import PairPicker from "../components/PairPicker";
import { f, pval, signed } from "../fmt";

type Set = (p: Record<string, string | null>, replace?: boolean) => void;

export default function Playback({ status, a, b, asOf, reveal, setParams }: {
  status: Status; a: string; b: string; asOf: string | null; reveal: boolean; setParams: Set }) {
  const [dates, setDates] = useState<string[]>([]);
  const [idx, setIdx] = useState<number>(-1);
  const [d, setD] = useState<PairDetail | null>(null);
  const [scan, setScan] = useState<Scanner | null>(null);
  const [rv, setRv] = useState<Reveal | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.calendar().then((c) => setDates(c.dates)).catch((e) => setErr(e.message)); }, []);
  // URL as-of -> slider index (snap to last session at or before the requested date)
  useEffect(() => {
    if (!dates.length) return;
    const target = asOf ?? dates[Math.floor(dates.length / 2)];
    let i = dates.length - 1;
    while (i > 0 && dates[i] > target) i--;
    setIdx(i);
  }, [dates, asOf]);
  const current = idx >= 0 ? dates[idx] : null;

  useEffect(() => {
    if (!current) return;
    const t = setTimeout(() => {
      setD(null); setScan(null); setErr(null);
      api.pair(a, b, current).then(setD).catch((e) => setErr(e.message));
      api.scanner(current).then(setScan).catch((e) => setErr(e.message));
    }, 180);
    return () => clearTimeout(t);
  }, [a, b, current]);

  useEffect(() => {
    setRv(null);
    if (reveal && current) api.reveal(a, b, current).then(setRv).catch((e) => setErr(e.message));
  }, [reveal, a, b, current]);

  const commit = (i: number) => setParams({ asof: dates[Math.max(0, Math.min(dates.length - 1, i))], reveal: null }, true);
  const step = (n: number) => commit(idx + n);

  return (
    <div className="playback">
      <div className="view-head">
        <div>
          <p className="eyebrow">Historical playback · point-in-time</p>
          <h2>{a} / {b}</h2>
        </div>
        <div className="head-actions">
          <PairPicker status={status} a={a} b={b} onChange={(x, y) => setParams({ a: x, b: y, reveal: null })} />
          {current && <a className="button primary" href={api.cardUrl(a, b, current)} download data-testid="export-card">Export PNG card</a>}
        </div>
      </div>

      <Panel className="timebar" testId="timebar">
        <div className="timebar-row">
          <label htmlFor="asof-slider" className="asof-label">As of <b data-testid="playback-asof">{current ?? "…"}</b></label>
          <input id="asof-slider" type="range" min={0} max={Math.max(0, dates.length - 1)} value={Math.max(0, idx)}
            onChange={(e) => { setIdx(Number(e.target.value)); if (reveal) setParams({ reveal: null }, true); }} onMouseUp={() => commit(idx)} onTouchEnd={() => commit(idx)}
            onKeyUp={() => commit(idx)} aria-label="As-of date" data-testid="asof-slider" />
          <input type="date" value={current ?? ""} min={dates[0]} max={dates[dates.length - 1]} aria-label="As-of date input"
            onChange={(e) => e.target.value && setParams({ asof: e.target.value, reveal: null }, true)} data-testid="asof-input" />
        </div>
        <div className="step-buttons">
          {[-63, -21, -5, -1, 1, 5, 21, 63].map((n) => (
            <button key={n} onClick={() => step(n)} aria-label={`Move ${n} sessions`}>{n > 0 ? `+${n}` : n}</button>
          ))}
        </div>
        <p className="panel-note">Every statistic, eligibility decision and sentence below is refitted on the {status.defaults.formation_window} sessions
          ending at the as-of date. Later observations are not used and are only shown after an explicit reveal.</p>
      </Panel>

      {err && <ErrorBox error={err} />}
      {(!d || !scan) && !err && <Loading what="as-of state" />}
      {d && scan && (
        <>
          <div className="asof-line"><ModeBadge mode={d.source_mode} /> State as of <b>{d.as_of}</b>: information available at that close only.</div>
          <KeyStats d={d} />
          <div className="grid-main">
            <div className="col">
              <ZChart d={d} testId="playback-z" />
              <Panel title={`Scanner as of ${scan.as_of}`} testId="playback-scanner"
                note={`${scan.family.method}; ${scan.family.family_size} tested, ${scan.family.n_eligible} eligible.`}>
                <div className="table-wrap">
                  <table className="data compact">
                    <thead><tr><th>Pair</th><th className="num">z</th><th className="num">BY adj. p</th><th>Eligible</th></tr></thead>
                    <tbody>
                      {[...scan.eligible, ...scan.excluded].map((r) => (
                        <tr key={r.pair} className={r.a === a && r.b === b ? "selected" : ""}
                          onClick={() => setParams({ a: r.a, b: r.b, reveal: null })}>
                          <td>{r.pair}</td><td className="num">{signed(r.z_last)}</td><td className="num">{pval(r.coint_p_adj)}</td>
                          <td>{r.eligible ? "yes" : <span className="fine">{r.exclusion_reasons[0]}</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {scan.eligible.length === 0 && <p className="empty">No eligible pairs at this date. Nothing is substituted.</p>}
              </Panel>
            </div>
            <div className="col side">
              <Explanation d={d} />
              <WhatChanged d={d} />
            </div>
          </div>

          {!reveal && (
            <div className="reveal-cta">
              <button className="reveal-btn" onClick={() => setParams({ reveal: "1" }, true)} data-testid="reveal-button">
                Reveal what happened next (63 sessions)
              </button>
              <span className="fine">The future is hidden until you ask for it.</span>
            </div>
          )}
          {reveal && <RevealPanel rv={rv} hide={() => setParams({ reveal: null }, true)} />}
        </>
      )}
    </div>
  );
}

function RevealPanel({ rv, hide }: { rv: Reveal | null; hide: () => void }) {
  const shapes = useMemo(() => bandShapes({ entry: 2, exit: 0.5, adverse: 3.5 }), []);
  return (
    <section className="future" data-testid="reveal-panel" aria-label="Future outcome">
      <div className="future-head">
        <span className="future-tag">FUTURE OUTCOME · not available at the as-of date</span>
        <button onClick={hide}>Hide</button>
      </div>
      {!rv && <Loading what="revealed outcome" />}
      {rv && !rv.available && <p>Nothing to reveal: {rv.reason}</p>}
      {rv && rv.available && rv.dates && (
        <>
          <p className="fine">{rv.note}</p>
          <div className="stats-row">
            <div className="stat"><div className="stat-label">z at as-of → end</div><div className="stat-value">{signed(rv.z_at_as_of)} → {signed(rv.z_at_end)}</div></div>
            <div className="stat"><div className="stat-label">First exit-band crossing</div><div className="stat-value" data-testid="reveal-crossing">{rv.first_exit_band_crossing ?? (rv.crossing_note ? "n/a" : "none")}</div>
              {rv.crossing_note && <div className="stat-hint">{rv.crossing_note}</div>}</div>
            <div className="stat"><div className="stat-label">Max adverse z</div><div className="stat-value">{f(rv.max_adverse_z)}</div></div>
            <div className="stat"><div className="stat-label">Hit ±3.5?</div><div className="stat-value">{rv.hit_adverse_threshold ? "yes" : "no"}</div></div>
          </div>
          <Chart ariaLabel="revealed future z path" data={[{ x: rv.dates, y: rv.z, type: "scatter", mode: "lines",
            name: "future z (frozen as-of parameters)", line: { color: C.future, width: 2, dash: "solid" } }]}
            layout={{ shapes, showlegend: false, plot_bgcolor: "#fffaf5", paper_bgcolor: "#fffaf5" }} />
          <p className="fine">{rv.sessions_available} sessions available{rv.gaps && rv.gaps.length ? `; gaps: ${rv.gaps.join(", ")}` : ""}.</p>
        </>
      )}
    </section>
  );
}
