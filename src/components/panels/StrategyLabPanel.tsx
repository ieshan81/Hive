"use client";

import { FlaskConical } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { Sparkline } from "@/components/ui/Sparkline";
import { cn } from "@/lib/utils";
import type { StrategyData } from "@/types/dashboard";

interface StrategyLabPanelProps {
  strategies: StrategyData[];
}

function statusStyles(status: StrategyData["status"]) {
  switch (status) {
    case "Active":
      return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
    case "Testing":
      return "bg-hive-cyan/15 text-hive-cyan border-hive-cyan/30";
    case "Cooling Down":
      return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  }
}

export function StrategyLabPanel({ strategies }: StrategyLabPanelProps) {
  return (
    <GlassPanel
      title="Strategy Lab"
      icon={<FlaskConical className="h-4 w-4" />}
      action={
        <button
          type="button"
          className="text-[10px] font-medium text-hive-cyan hover:text-hive-cyan/80 transition"
        >
          Manage Strategies
        </button>
      }
    >
      {strategies.length === 0 ? (
        <EmptyState message="No strategy states yet — run POST /api/cycle/run" />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-4 gap-3 auto-rows-fr">
        {strategies.map((strategy) => (
          <div
            key={strategy.id}
            className="flex flex-col rounded-lg border border-white/5 bg-white/2 p-3 hover:border-hive-cyan/20 transition h-full min-h-[140px]"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-white">{strategy.name}</span>
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[8px] font-bold tracking-wider border",
                  statusStyles(strategy.status)
                )}
              >
                {strategy.status}
              </span>
            </div>

            <div className="flex items-end justify-between mb-2">
              <div>
                <p className="text-[9px] text-slate-500 uppercase">Perf (7D)</p>
                <p
                  className={cn(
                    "text-sm font-bold",
                    strategy.performance7d === null
                      ? "text-slate-500"
                      : strategy.performance7d >= 0
                        ? "text-emerald-400"
                        : "text-red-400"
                  )}
                >
                  {strategy.performance7d === null
                    ? "—"
                    : `${strategy.performance7d >= 0 ? "+" : ""}${strategy.performance7d.toFixed(1)}%`}
                </p>
              </div>
              {strategy.sparkline.length > 0 && (
              <Sparkline
                data={strategy.sparkline}
                color={(strategy.performance7d ?? 0) >= 0 ? "#10b981" : "#ef4444"}
                width={48}
                height={20}
              />
              )}
            </div>

            <div className="space-y-2">
              <div>
                <div className="flex justify-between text-[9px] mb-0.5">
                  <span className="text-slate-500">Confidence</span>
                  <span className="text-slate-400">{strategy.confidence}%</span>
                </div>
                <div className="h-1 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-hive-cyan/70"
                    style={{ width: `${strategy.confidence}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-[9px] mb-0.5">
                  <span className="text-slate-500">Exposure</span>
                  <span className="text-slate-400">{strategy.exposure}%</span>
                </div>
                <div className="h-1 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-hive-violet/70"
                    style={{ width: `${strategy.exposure}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        ))}
        </div>
      )}
    </GlassPanel>
  );
}
