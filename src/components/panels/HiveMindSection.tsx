"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, Sparkles } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { HiveMemoryGraphPanel } from "@/components/panels/HiveMemoryGraphPanel";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function HiveMindSection() {
  const [mind, setMind] = useState<{
    trading_recent?: { title: string; category: string; severity: string }[];
    system_recent?: { title: string }[];
    patterns?: { title: string; occurrence_count: number }[];
    ai_review_freshness?: {
      latest_cycle_run_id?: string;
      review_cycle_run_id?: string;
      freshness?: string;
      skip_reason?: string;
    };
  } | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/memory/hive-mind`);
      setMind(await res.json());
    } catch {
      setMind(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const fr = mind?.ai_review_freshness;
  const freshnessClass =
    fr?.freshness === "latest"
      ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
      : fr?.freshness === "stale"
        ? "text-amber-400 border-amber-500/30 bg-amber-500/10"
        : "text-slate-400 border-white/10 bg-white/5";

  return (
    <section className="space-y-5 mt-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-hive-violet/15 border border-hive-violet/25">
            <Brain className="h-5 w-5 text-hive-violet" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">Hive Mind</h2>
            <p className="text-[10px] text-slate-500">Evidence memories feeding the core intelligence</p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-[10px] text-slate-400 cursor-pointer rounded-full border border-white/10 px-3 py-1.5 hover:border-white/20">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="accent-hive-cyan"
          />
          Show archived
        </label>
      </header>

      <div className="flex flex-wrap gap-2 text-[10px]">
        <span className={`rounded-full border px-2.5 py-1 font-mono ${freshnessClass}`}>
          AI {fr?.freshness ?? "—"}
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-400">
          Cycle <span className="text-slate-300 font-mono">{fr?.latest_cycle_run_id?.slice(0, 8) ?? "—"}</span>
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-400">
          Review <span className="text-slate-300 font-mono">{fr?.review_cycle_run_id?.slice(0, 8) ?? "none"}</span>
        </span>
        {fr?.skip_reason && (
          <span className="rounded-full border border-amber-500/20 bg-amber-500/5 px-2.5 py-1 text-amber-300/90">
            {fr.skip_reason}
          </span>
        )}
      </div>

      <HiveMemoryGraphPanel compact showArchived={showArchived} categoryFilter="all" />

      <div className="grid md:grid-cols-3 gap-3">
        <GlassPanel title="Trading memories" className="!p-3">
          <ul className="text-xs space-y-2 max-h-36 overflow-y-auto scrollbar-thin">
            {(mind?.trading_recent || []).length === 0 ? (
              <li className="text-slate-600">None yet</li>
            ) : (
              (mind?.trading_recent || []).map((l) => (
                <li key={l.title} className="flex gap-2 text-slate-300 border-b border-white/5 pb-1.5 last:border-0">
                  <Sparkles className="h-3 w-3 text-cyan-400 flex-shrink-0 mt-0.5" />
                  <span className="leading-snug">{l.title}</span>
                </li>
              ))
            )}
          </ul>
        </GlassPanel>
        <GlassPanel title="System issues" className="!p-3">
          <ul className="text-xs space-y-2 max-h-36 overflow-y-auto scrollbar-thin">
            {(mind?.system_recent || []).length === 0 ? (
              <li className="text-slate-600">None active</li>
            ) : (
              (mind?.system_recent || []).map((l) => (
                <li key={l.title} className="text-orange-200/85 border-b border-orange-500/10 pb-1.5 last:border-0 leading-snug">
                  {l.title}
                </li>
              ))
            )}
          </ul>
        </GlassPanel>
        <GlassPanel title="Patterns" className="!p-3">
          <ul className="text-xs space-y-1.5 max-h-36 overflow-y-auto scrollbar-thin">
            {(mind?.patterns || []).length === 0 ? (
              <li className="text-slate-600">No recurring patterns</li>
            ) : (
              (mind?.patterns || []).map((p) => (
                <li key={p.title} className="flex justify-between gap-2 text-slate-400">
                  <span className="truncate">{p.title}</span>
                  <span className="text-amber-400 font-mono flex-shrink-0">×{p.occurrence_count}</span>
                </li>
              ))
            )}
          </ul>
        </GlassPanel>
      </div>
    </section>
  );
}
