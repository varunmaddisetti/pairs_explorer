import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";

/* Single-axis charts only; colors follow entity, never rank. */
export const C = {
  a: "#2a78d6", b: "#eb6834", aqua: "#1baf7a", violet: "#4a3aa7", ink: "#1d1c1a", ink2: "#52514e",
  muted: "#8a8984", grid: "#ebe9e3", surface: "#fffefb", band: "#f0efec", future: "#7a2e0e",
};

const base: Partial<Plotly.Layout> = {
  margin: { l: 52, r: 16, t: 12, b: 36 },
  paper_bgcolor: C.surface, plot_bgcolor: C.surface,
  font: { family: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size: 12, color: C.ink2 },
  xaxis: { gridcolor: C.grid, linecolor: C.grid, zeroline: false, automargin: true },
  yaxis: { gridcolor: C.grid, linecolor: C.grid, zeroline: false, automargin: true },
  hovermode: "x unified", hoverlabel: { bgcolor: "#fff", bordercolor: C.grid, font: { color: C.ink } },
  legend: { orientation: "h", y: 1.12, x: 0, font: { size: 12 } },
  dragmode: false,
};

export function Chart({ data, layout, height = 280, testId, ariaLabel }: {
  data: Partial<Plotly.Data>[]; layout?: Partial<Plotly.Layout>; height?: number; testId?: string; ariaLabel: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const l = { ...base, ...layout, height,
      xaxis: { ...base.xaxis, ...(layout?.xaxis ?? {}) }, yaxis: { ...base.yaxis, ...(layout?.yaxis ?? {}) } };
    Plotly.react(el, data as Plotly.Data[], l, {
      responsive: true, displaylogo: false, scrollZoom: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines", "zoomIn2d", "zoomOut2d"],
    });
  }, [data, layout, height]);
  useEffect(() => () => { if (ref.current) Plotly.purge(ref.current); }, []);
  return <div className="chart" ref={ref} data-testid={testId} role="img" aria-label={ariaLabel} />;
}

export function bandShapes(b: { entry: number; exit: number; adverse: number }): Partial<Plotly.Shape>[] {
  const line = (y: number, dash: Plotly.Dash, color = C.muted): Partial<Plotly.Shape> => ({
    type: "line" as const, xref: "paper" as const, x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1, dash } });
  return [line(0, "solid", C.ink2), line(b.entry, "dash"), line(-b.entry, "dash"), line(b.exit, "dot"),
    line(-b.exit, "dot"), line(b.adverse, "dashdot"), line(-b.adverse, "dashdot")];
}
