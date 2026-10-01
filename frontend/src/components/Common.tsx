import type { ReactNode } from "react";
import type { Labels, Mode } from "../api";

export function ModeBadge({ mode, large = false }: { mode: Mode; large?: boolean }) {
  const text = mode === "SYNTHETIC_DEMO" ? "SYNTHETIC DEMO" : mode === "REAL_UNVALIDATED" ? "REAL · NOT VALIDATED"
    : "REAL · RESEARCH-VALIDATED";
  return <span className={`mode-badge mode-${mode} ${large ? "large" : ""}`} data-testid="mode-badge">{text}</span>;
}

export function Stat({ label, value, hint, testId }: { label: string; value: ReactNode; hint?: string; testId?: string }) {
  return (
    <div className="stat" data-testid={testId}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function LabelChips({ labels }: { labels: Labels }) {
  const rows: [string, string][] = [
    ["Relationship evidence", labels.relationship_evidence],
    ["Observed divergence", labels.observed_divergence],
    ["Data quality", labels.data_quality],
    ["Execution assumptions", labels.execution_assumptions],
  ];
  return (
    <dl className="label-grid" data-testid="labels">
      {rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
    </dl>
  );
}

export function Panel({ title, children, note, className = "", testId }: {
  title?: ReactNode; children: ReactNode; note?: ReactNode; className?: string; testId?: string }) {
  return (
    <section className={`panel ${className}`} data-testid={testId}>
      {title && <h3 className="panel-title">{title}</h3>}
      {children}
      {note && <p className="panel-note">{note}</p>}
    </section>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="error" role="alert">Could not load: {error}</div>;
}

export function Loading({ what }: { what: string }) {
  return <div className="loading" aria-live="polite">Loading {what}…</div>;
}
