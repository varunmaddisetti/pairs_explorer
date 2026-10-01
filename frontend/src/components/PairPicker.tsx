import type { Status } from "../api";

export default function PairPicker({ status, a, b, onChange }: {
  status: Status; a: string; b: string; onChange: (a: string, b: string) => void }) {
  return (
    <label className="picker">
      <span className="sr-only">Pair</span>
      <select value={`${a}|${b}`} onChange={(e) => { const [x, y] = e.target.value.split("|"); onChange(x, y); }}
        data-testid="pair-picker" aria-label="Choose pair">
        {status.candidate_pairs.map((p) => (
          <option key={`${p.a}|${p.b}`} value={`${p.a}|${p.b}`}>{p.a} / {p.b} ({p.group})</option>
        ))}
      </select>
    </label>
  );
}
