"use client";

import { useCallback, useEffect, useState } from "react";
import { LineChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type Point = { t: string | null; equity: number; cash?: number; drawdown_pct?: number };
type Curve = {
  points?: Point[];
  count?: number;
  start_equity?: number;
  current_equity?: number;
  change_usd?: number;
  change_pct?: number | null;
  max_drawdown_pct?: number;
};
type Summary = {
  pl_dollars?: number;
  closed_trades?: number;
  win_rate_pct?: number | null;
};

/** Compact equity sparkline (no charting dependency) — green if up over the window. */
function Sparkline({ points }: { points: Point[] }) {
  const vals = points.map((p) => Number(p.equity) || 0);
  if (vals.length < 2) return null;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const w = 240;
  const h = 48;
  const step = w / (vals.length - 1);
  const d = vals
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`)
    .join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full">
      <path d={d} fill="none" stroke={up ? "#00FF66" : "#EF4444"} strokeWidth="1.5" />
    </svg>
  );
}

/**
 * Cockpit Portfolio History card — read-only. Renders the paper equity curve,
 * change, max drawdown and realized P/L from /api/performance/* . Never mutates state.
 */
export function CockpitPortfolioHistory() {
  const [curve, setCurve] = useState<Curve | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);

  const load = useCallback(async () => {
    const [c, s] = await Promise.all([
      apiGet<Curve>("/api/performance/equity-curve?limit=120", { timeoutMs: 6000 }),
      apiGet<Summary>("/api/performance/summary", { timeoutMs: 6000 }),
    ]);
    if (c.ok && c.data) setCurve(c.data);
    if (s.ok && s.data) setSummary(s.data);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const points = curve?.points ?? [];
  const hasData = points.length > 0;
  const change = curve?.change_usd ?? 0;
  const changePct = curve?.change_pct;
  const up = change >= 0;
  const pl = summary?.pl_dollars ?? 0;

  return (
    <GlassPanel title="Portfolio History" icon={<LineChart className="h-4 w-4" />}>
      {!hasData ? (
        <p className="text-xs text-slate-500">
          No equity snapshots yet — the curve appears once paper account snapshots accumulate.
        </p>
      ) : (
        <>
          <Sparkline points={points} />
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            {([
              ["Current", curve?.current_equity != null ? `$${curve.current_equity.toFixed(2)}` : "—", "#ffffff"],
              [
                "Change",
                `${up ? "+" : ""}${change.toFixed(2)}${changePct != null ? ` (${changePct}%)` : ""}`,
                up ? "#00FF66" : "#EF4444",
              ],
              ["Max drawdown", curve?.max_drawdown_pct != null ? `${curve.max_drawdown_pct}%` : "—", "#F59E0B"],
              ["Realized P/L", summary?.pl_dollars != null ? `$${pl.toFixed(2)}` : "—", pl >= 0 ? "#00FF66" : "#EF4444"],
            ] as [string, string, string][]).map(([label, val, color]) => (
              <div key={label} className="rounded-lg border border-white/5 bg-white/[0.02] p-2">
                <p className="text-[10px] uppercase text-slate-500">{label}</p>
                <p className="font-bold mono-metric" style={{ color }}>
                  {val}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[10px] text-slate-500">
            {curve?.count ?? points.length} snapshot(s) · start $
            {curve?.start_equity != null ? curve.start_equity.toFixed(2) : "—"} · {summary?.closed_trades ?? 0} closed
            trades{summary?.win_rate_pct != null ? ` · win ${summary.win_rate_pct}%` : ""}
          </p>
        </>
      )}
    </GlassPanel>
  );
}
