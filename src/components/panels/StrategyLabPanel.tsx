"use client";

import Link from "next/link";
import { FlaskConical, GitCompare, Moon, TrendingUp } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { cn } from "@/lib/utils";
import type { StrategyData } from "@/types/dashboard";

interface StrategyLabPanelProps {
  strategies: StrategyData[];
}

const STRATEGY_ICONS: Record<string, typeof TrendingUp> = {
  momentum_orb: TrendingUp,
  mean_reversion_pairs: GitCompare,
  crypto_night_momentum: Moon,
};

function statusStyles(status: string) {
  const s = status.toLowerCase();
  if (s === "active") return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  if (s === "testing") return "bg-hive-cyan/15 text-hive-cyan border-hive-cyan/30";
  if (s === "cooling down") return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  return "bg-slate-500/15 text-slate-400 border-slate-500/30";
}

function StatPill({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-md border border-white/5 bg-white/[0.03] px-2 py-1.5 min-w-[4.5rem]">
      <p className="text-[8px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={cn("text-xs font-semibold tabular-nums", accent ? "text-emerald-400" : "text-slate-300")}>{value}</p>
    </div>
  );
}

function StrategyCard({ strategy }: { strategy: StrategyData }) {
  const Icon = STRATEGY_ICONS[strategy.id] ?? FlaskConical;
  const perf =
    strategy.performance7d === null
      ? "—"
      : `${strategy.performance7d >= 0 ? "+" : ""}${strategy.performance7d.toFixed(1)}%`;
  const perfPositive = strategy.performance7d !== null && strategy.performance7d >= 0;

  return (
    <li className="rounded-lg border border-white/5 bg-white/[0.02] p-3 hover:border-hive-cyan/15 transition-colors">
      <div className="flex gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-hive-cyan/10 text-hive-cyan ring-1 ring-hive-cyan/20">
          <Icon className="h-4 w-4" strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-2">
            <p className="text-xs font-semibold text-white leading-snug">{strategy.name}</p>
            <span
              className={cn(
                "self-start shrink-0 rounded border px-2 py-0.5 text-[8px] font-bold uppercase tracking-wide whitespace-nowrap",
                statusStyles(strategy.status)
              )}
            >
              {strategy.status}
            </span>
          </div>
          {strategy.message && (
            <p className="mt-1 text-[10px] leading-relaxed text-slate-500 line-clamp-2">{strategy.message}</p>
          )}
          <div className="mt-2.5 flex flex-wrap gap-2">
            <StatPill
              label="Perf 7D"
              value={perf}
              accent={strategy.performance7d !== null && perfPositive}
            />
            <StatPill label="Confidence" value={`${strategy.confidence}%`} />
            <StatPill label="Exposure" value={`${strategy.exposure}%`} />
          </div>
        </div>
      </div>
    </li>
  );
}

export function StrategyLabPanel({ strategies }: StrategyLabPanelProps) {
  return (
    <GlassPanel
      title="Strategy Lab"
      icon={<FlaskConical className="h-4 w-4" />}
      action={
        <Link href="/strategies" className="text-[10px] font-medium text-hive-cyan hover:text-hive-cyan/80 transition">
          Manage Strategies
        </Link>
      }
      className="h-full"
    >
      {strategies.length === 0 ? (
        <EmptyState message="No strategy states yet — run POST /api/cycle/run" />
      ) : (
        <ul className="space-y-2">
          {strategies.map((strategy) => (
            <StrategyCard key={strategy.id} strategy={strategy} />
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
