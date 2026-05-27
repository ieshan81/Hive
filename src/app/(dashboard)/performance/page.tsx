"use client";

import { useCallback, useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";

export default function PerformancePage() {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [points, setPoints] = useState<{ t?: string; equity?: number }[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [s, c] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/performance/summary"),
      apiGet<{ points?: { t?: string; equity?: number }[]; fresh_baseline_label?: string }>(
        "/api/performance/equity-curve"
      ),
    ]);
    if (s.ok) setSummary(s.data);
    if (c.ok) setPoints(c.data?.points ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => onHiveNukeComplete(() => void load()), [load]);

  if (loading) return <EmptyState message="Loading performance…" className="min-h-[240px]" />;

  const maxEq = Math.max(...points.map((p) => p.equity ?? 0), summary?.current_equity as number ?? 1);

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <BarChart3 className="h-6 w-6 text-hive-cyan" />
        Performance
      </h1>
      <p className="text-sm text-slate-400">{String(summary?.fresh_baseline_label ?? "Post-reset paper performance")}</p>

      <div className="grid gap-4 md:grid-cols-3">
        <GlassPanel title="Equity">
          <p className="text-2xl font-bold text-white">${Number(summary?.current_equity ?? 0).toLocaleString()}</p>
          <p className="text-[11px] text-slate-500">P/L ${Number(summary?.pl_dollars ?? 0).toFixed(2)}</p>
        </GlassPanel>
        <GlassPanel title="Trades">
          <p className="text-2xl font-bold text-white">{String(summary?.trades_count ?? 0)}</p>
          <p className="text-[11px] text-slate-500">
            W {String(summary?.wins ?? 0)} / L {String(summary?.losses ?? 0)}
          </p>
        </GlassPanel>
        <GlassPanel title="Win rate">
          <p className="text-2xl font-bold text-white">
            {summary?.win_rate_pct != null ? `${summary.win_rate_pct}%` : "—"}
          </p>
        </GlassPanel>
      </div>

      <GlassPanel title="Equity curve">
        {points.length === 0 ? (
          <p className="text-sm text-slate-500">
            No closed paper trades after reset yet. Performance is based on open broker position only.
          </p>
        ) : (
          <svg viewBox="0 0 400 120" className="w-full h-32 text-cyan-400" preserveAspectRatio="none">
            <polyline
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              points={points
                .map((p, i) => {
                  const x = (i / Math.max(points.length - 1, 1)) * 400;
                  const y = 110 - ((p.equity ?? 0) / maxEq) * 100;
                  return `${x},${y}`;
                })
                .join(" ")}
            />
            <polygon
              fill="currentColor"
              fillOpacity="0.12"
              points={`0,120 ${points
                .map((p, i) => {
                  const x = (i / Math.max(points.length - 1, 1)) * 400;
                  const y = 110 - ((p.equity ?? 0) / maxEq) * 100;
                  return `${x},${y}`;
                })
                .join(" ")} 400,120`}
            />
          </svg>
        )}
      </GlassPanel>
    </section>
  );
}
