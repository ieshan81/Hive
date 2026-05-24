"use client";

import { AlertTriangle, LineChart } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import type { MonteCarloData } from "@/types/dashboard";

interface MonteCarloPanelProps {
  data: MonteCarloData;
  backtestMessage?: string;
}

export function MonteCarloPanel({ data, backtestMessage }: MonteCarloPanelProps) {
  const unavailable = data.status !== "ok" || data.medianPath.length === 0;
  const chartData = data.medianPath.map((median, day) => ({ day, median: Math.round(median) }));

  return (
    <GlassPanel title="Backtest + Monte Carlo Projection" icon={<LineChart className="h-4 w-4" />}>
      <p className="text-xs font-semibold tracking-wider text-hive-cyan mb-4 uppercase">
        Goal: Growth from ${data.goalFrom ?? "—"} to ${data.goalTo}
      </p>

      {unavailable ? (
        <EmptyState message={data.message ?? "Monte Carlo unavailable — not enough real trade data"} className="min-h-[200px] mb-4" />
      ) : (
        <section className="grid grid-cols-1 xl:grid-cols-[1fr_280px] gap-4">
          <figure className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="medianGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00d1ff" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#8a2be2" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="3 3" />
                <XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => `${v}D`} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => `$${v}`} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: "rgba(8,12,20,0.95)", border: "1px solid rgba(0,209,255,0.2)", borderRadius: 8, fontSize: 11 }} labelFormatter={(v) => `Day ${v}`} formatter={(value: number) => [`$${value}`, "Median"]} />
                <Area type="monotone" dataKey="median" stroke="#ffffff" strokeWidth={2} fill="url(#medianGrad)" dot={false} />
                {data.goalFrom !== null && <ReferenceLine y={data.goalFrom} stroke="#64748b" strokeDasharray="4 4" />}
                <ReferenceLine y={data.goalTo} stroke="#10b981" strokeDasharray="4 4" />
              </AreaChart>
            </ResponsiveContainer>
          </figure>
          <aside className="space-y-4">
            <article className="rounded-lg border border-white/5 bg-white/2 p-3">
              <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Probability of Reaching ${data.goalTo}</p>
              <p className="text-2xl font-bold text-white">
                {data.probabilityPct !== null ? `${data.probabilityPct.toFixed(1)}%` : "—"}
                <span className="text-xs font-normal text-slate-400 ml-1">within {data.horizonDays} days</span>
              </p>
            </article>
            <article className="rounded-lg border border-white/5 bg-white/2 p-3">
              <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Drawdown Risk (Max)</p>
              <p className="text-xl font-bold text-amber-400">
                {data.maxDrawdownPct !== null ? `${data.maxDrawdownPct.toFixed(1)}%` : "—"}
                <span className="text-xs font-normal text-slate-400 ml-1">at {data.drawdownConfidence}% confidence</span>
              </p>
            </article>
            {data.scenarios.length > 0 && (
              <article className="rounded-lg border border-white/5 bg-white/2 p-3">
                <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-2">Scenario Outcomes ({data.horizonDays}D)</p>
                <ul className="space-y-1.5">
                  {data.scenarios.map((s) => (
                    <li key={s.percentile} className="flex justify-between text-xs">
                      <span className="text-slate-400">{s.percentile}</span>
                      <span className="font-semibold text-white">${s.value}</span>
                    </li>
                  ))}
                </ul>
              </article>
            )}
          </aside>
        </section>
      )}

      {backtestMessage && (
        <p className="text-[10px] text-slate-500 mt-3">Backtest: {backtestMessage}</p>
      )}

      <footer className="flex items-start gap-2 mt-4 pt-3 border-t border-white/5">
        <AlertTriangle className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
        <p className="text-[10px] text-slate-500 leading-relaxed">
          {data.message ?? "Projections use real logged trade outcomes only. Not guarantees of future performance."}
        </p>
      </footer>
    </GlassPanel>
  );
}
