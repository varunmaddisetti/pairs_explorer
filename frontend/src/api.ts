// Thin typed client. All numbers shown in the UI come from these backend responses.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type Mode = "SYNTHETIC_DEMO" | "REAL_UNVALIDATED" | "REAL_RESEARCH_VALIDATED";

export interface Labels {
  relationship_evidence: string;
  observed_divergence: string;
  data_quality: string;
  execution_assumptions: string;
}

export interface PairRow {
  a: string; b: string; pair: string; group: string; status: string; skip_reason?: string;
  n_obs: number; alpha?: number; beta?: number; mu?: number; sigma?: number; z_last?: number;
  coint_stat?: number; coint_p?: number; coint_p_adj?: number; coint_crit_5pct?: number;
  coint_crit_1pct?: number; coint_crit_10pct?: number; coint_maxlag?: number;
  half_life?: number | null; hl_status?: string; rho?: number | null; return_corr?: number | null;
  eligible: boolean; exclusion_reasons: string[]; fdr_reject?: boolean; formation_start?: string;
  formation_end: string; last_observation?: string; labels?: Labels; unit_root?: any[];
}

export interface Family { family_size: number; n_candidates: number; n_skipped: number; n_eligible: number; method: string }

export interface Status {
  mode: Mode; statuses: Record<string, boolean>; source: string; dataset_id: string; dataset_content_sha256: string;
  first_date: string; last_date: string; sessions: number; calendar: string; symbols: string[];
  groups: Record<string, string[]>; universe_version: string; candidate_pairs: { a: string; b: string; group: string }[];
  manifest: Record<string, any>; display_policy: Record<string, any>; defaults: Record<string, any>; params_hash: string;
}

export interface Scanner { as_of: string; family: Family; eligible: PairRow[]; excluded: PairRow[]; ranking: string; mode: Mode }

export interface PairDetail {
  pair: string; a: string; b: string; as_of: string; source_mode: Mode; dataset_id: string; group: string;
  stats: PairRow; family: Family; labels: Labels;
  descriptive: { dates: string[]; norm_a: (number | null)[]; norm_b: (number | null)[]; ratio: (number | null)[];
    rolling_corr: (number | null)[]; drawdown_a: (number | null)[]; drawdown_b: (number | null)[];
    full_period_return_corr: number | null; gaps: string[]; note: string };
  formation: null | { dates: string[]; spread: number[]; z: number[]; calibration_start: string;
    bands: { entry: number; exit: number; adverse: number } };
  beta_history: { history: { formation_end: string; fold: number; beta: number | null; coint_p: number | null;
    coint_p_adj: number | null; eligible: boolean }[]; warnings: string[]; rule: string };
  walk_forward: { dates: string[]; z: (number | null)[]; fold: number[] };
  explanation: string[]; what_changed: string[]; available_until: string;
}

export interface Reveal {
  pair: string; as_of: string; available: boolean; reason?: string; sessions_available: number; note: string;
  dates?: string[]; z?: (number | null)[]; norm_a?: number[]; norm_b?: number[]; z_at_as_of?: number; z_at_end?: number;
  first_exit_band_crossing?: string | null; crossing_note?: string | null; max_adverse_z?: number | null; hit_adverse_threshold?: boolean; gaps?: string[];
}

export interface Curated { teaching: Example | null; contrast: Example | null; note: string }
export interface Example { kind: string; a: string; b: string; as_of: string; summary: string }

export type Backtest = Record<string, any>;

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = j.detail ?? JSON.stringify(j); } catch { /* not json */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

const q = (o: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => [k, String(v)])).toString();

export const api = {
  status: () => get<Status>("/api/status"),
  calendar: () => get<{ dates: string[]; calendar: string }>("/api/calendar"),
  curated: () => get<Curated>("/api/curated"),
  scanner: (as_of?: string) => get<Scanner>(`/api/scanner?${q({ as_of })}`),
  pair: (a: string, b: string, as_of?: string) => get<PairDetail>(`/api/pair?${q({ a, b, as_of })}`),
  reveal: (a: string, b: string, as_of: string, horizon = 63) => get<Reveal>(`/api/reveal?${q({ a, b, as_of, horizon })}`),
  diagnostics: () => get<Record<string, any>>("/api/diagnostics"),
  experiments: () => get<Record<string, any>>("/api/experiments"),
  cardUrl: (a: string, b: string, as_of?: string) => `/api/card.png?${q({ a, b, as_of })}`,
  bundleUrl: (runId: string) => `/api/backtest/${runId}/bundle.zip`,
  backtest: async (body: { a: string; b: string; strict: boolean; params: Record<string, number | string> }) => {
    const r = await fetch("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(`${r.status}: ${typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j)}`);
    return j as Backtest;
  },
};
