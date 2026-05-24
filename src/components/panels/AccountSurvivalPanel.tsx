"use client";

import { Shield } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { Sparkline } from "@/components/ui/Sparkline";
import type { AccountSurvivalData } from "@/types/dashboard";

interface AccountSurvivalPanelProps {
  data: AccountSurvivalData;
}

export function AccountSurvivalPanel({ data }: AccountSurvivalPanelProps) {
  const hasData = data.status === "ok" && data.capital !== null;
  const dailyPct = data.dailyLossLimit > 0 ? (data.dailyLossUsed / data.dailyLossLimit) * 100 : 0;
  const weeklyPct = data.weeklyLossLimit > 0 ? (data.weeklyLossUsed / data.weeklyLossLimit) * 100 : 0;

  return (
    <GlassPanel title="Account Survival" icon={<Shield className="h-4 w-4" />} className="h-full">
      {!hasData ? (
        <EmptyState message={data.message ?? "Waiting for Alpaca sync"} />
      ) : (
        <>
          <section className="grid grid-cols-3 gap-4 mb-4">
            <article className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Capital</span>
              <span className="text-lg font-bold text-white">${data.capital!.toFixed(2)}</span>
              {data.sparklines.capital.length > 0 && (
                <Sparkline data={data.sparklines.capital} color="#00d1ff" width={72} height={22} />
              )}
            </article>
            <article className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-slate-500">P/L Today</span>
              <span className={`text-lg font-bold ${(data.plToday ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {data.plToday !== null ? `${data.plToday >= 0 ? "+" : ""}$${data.plToday.toFixed(2)}` : "—"}
              </span>
              {data.plTodayPct !== null && (
                <span className={`text-xs ${data.plTodayPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {data.plTodayPct >= 0 ? "+" : ""}{data.plTodayPct.toFixed(2)}%
                </span>
              )}
            </article>
            <article className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Drawdown</span>
              <span className="text-lg font-bold text-white">
                {data.drawdown !== null ? `${data.drawdown.toFixed(2)}%` : "—"}
              </span>
            </article>
          </section>

          <section className="flex items-center gap-2 mb-3">
            <span className="rounded px-2 py-0.5 text-[10px] font-bold tracking-wider bg-hive-cyan/15 text-hive-cyan border border-hive-cyan/30">
              {data.riskStatus}
            </span>
            <span className="text-xs text-slate-400">{data.riskStatusMessage}</span>
          </section>

          <section className="mb-4">
            <header className="flex justify-between text-[9px] text-slate-500 mb-1 uppercase tracking-wider">
              <span>Low Risk</span>
              <span>High Risk</span>
            </header>
            <figure className="relative h-2 rounded-full overflow-hidden bg-white/5">
              <span className="absolute inset-0 rounded-full block" style={{ background: "linear-gradient(90deg, #10b981 0%, #f59e0b 50%, #ef4444 100%)" }} />
              <span className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2 border-white bg-hive-cyan block" style={{ left: `calc(${data.riskLevel}% - 6px)` }} />
            </figure>
          </section>

          <section className="space-y-3 mb-4">
            <article>
              <header className="flex justify-between text-[10px] mb-1">
                <span className="text-slate-500">Daily Loss Limit</span>
                <span className="text-slate-300">${data.dailyLossUsed.toFixed(2)} / ${data.dailyLossLimit.toFixed(2)}</span>
              </header>
              <figure className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                <span className="h-full rounded-full bg-gradient-to-r from-hive-cyan to-hive-violet block" style={{ width: `${Math.min(100, dailyPct)}%` }} />
              </figure>
            </article>
            <article>
              <header className="flex justify-between text-[10px] mb-1">
                <span className="text-slate-500">Weekly Loss Limit</span>
                <span className="text-slate-300">${data.weeklyLossUsed.toFixed(2)} / ${data.weeklyLossLimit.toFixed(2)}</span>
              </header>
              <figure className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                <span className="h-full rounded-full bg-gradient-to-r from-hive-cyan to-hive-violet block" style={{ width: `${Math.min(100, weeklyPct)}%` }} />
              </figure>
            </article>
          </section>
        </>
      )}
      <p className="text-xs italic text-hive-cyan/80 text-center mt-2">Survival First. Profit Follows.</p>
    </GlassPanel>
  );
}
