export const f = (x: number | null | undefined, d = 2, none = "n/a") =>
  x === null || x === undefined || !Number.isFinite(x) ? none : x.toFixed(d);
export const signed = (x: number | null | undefined, d = 2) =>
  x === null || x === undefined || !Number.isFinite(x) ? "n/a" : (x >= 0 ? "+" : "") + x.toFixed(d);
export const pct = (x: number | null | undefined, d = 2) =>
  x === null || x === undefined || !Number.isFinite(x) ? "n/a" : `${(x * 100).toFixed(d)}%`;
export const inr = (x: number | null | undefined, d = 0) =>
  x === null || x === undefined || !Number.isFinite(x) ? "n/a"
    : (x < 0 ? "−₹" : "₹") + Math.abs(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
export const pval = (x: number | null | undefined) =>
  x === null || x === undefined ? "n/a" : x < 0.001 ? "<0.001" : x.toFixed(3);
