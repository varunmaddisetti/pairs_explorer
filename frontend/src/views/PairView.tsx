import { useEffect, useState } from "react";
import { api, type PairDetail, type Status } from "../api";
import { ErrorBox, Loading, ModeBadge } from "../components/Common";
import { CorrChart, Diagnostics, Explanation, KeyStats, MoreDescriptive, PriceChart, SpreadChart, WalkForward,
  WhatChanged, ZChart } from "../components/PairPanels";
import PairPicker from "../components/PairPicker";

type Set = (p: Record<string, string | null>, replace?: boolean) => void;

export default function PairView({ status, a, b, asOf, setParams }: {
  status: Status; a: string; b: string; asOf: string | null; setParams: Set }) {
  const [d, setD] = useState<PairDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setD(null); setErr(null);
    api.pair(a, b, asOf ?? undefined).then(setD).catch((e) => setErr(e.message));
  }, [a, b, asOf]);
  return (
    <div className="pairview">
      <div className="view-head">
        <div>
          <p className="eyebrow">Pair detail {asOf ? `· as of ${asOf}` : "· latest available session"}</p>
          <h2 data-testid="pair-title">{a} / {b}</h2>
        </div>
        <div className="head-actions">
          <PairPicker status={status} a={a} b={b} onChange={(x, y) => setParams({ a: x, b: y }, false)} />
          {d && <>
            <a className="button primary" href={api.cardUrl(a, b, d.as_of)} download data-testid="export-card">Export PNG card</a>
            <button onClick={() => setParams({ view: "playback", asof: d.as_of })}>Replay history</button>
            <button onClick={() => setParams({ view: "backtest", asof: null })}>Backtest</button>
          </>}
        </div>
      </div>
      {err && <ErrorBox error={err} />}
      {!d && !err && <Loading what="pair statistics" />}
      {d && <>
        <div className="asof-line">
          <ModeBadge mode={d.source_mode} /> As of <b data-testid="pair-asof">{d.as_of}</b> · group {d.group} · data available until {d.available_until}
        </div>
        <KeyStats d={d} />
        <div className="grid-main">
          <div className="col">
            <ZChart d={d} />
            <PriceChart d={d} />
            <CorrChart d={d} />
          </div>
          <div className="col side">
            <Explanation d={d} />
            <WhatChanged d={d} />
          </div>
        </div>
        <div className="grid2">
          <SpreadChart d={d} />
          <WalkForward d={d} />
        </div>
        <MoreDescriptive d={d} />
        <Diagnostics d={d} />
      </>}
    </div>
  );
}
