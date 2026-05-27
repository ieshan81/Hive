"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, Sparkles } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { HiveMemoryGraphPanel } from "@/components/panels/HiveMemoryGraphPanel";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";
import { PanelError } from "@/components/ui/PanelError";
import type { PanelLoadMeta } from "@/types/api";

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
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });
  const [showArchived, setShowArchived] = useState(false);

  const load = useCallback(async () => {
    const result = await apiGet<Record<string, unknown>>("/api/page-state/ai-manager");
    if (result.ok && result.data) {
      setMind(result.data as typeof mind);
      setMeta({
        source: "live_api",
        lastUpdated: new Date().toISOString(),
        endpoint: "/api/memory/hive-mind",
        httpStatus: result.status,
      });
    } else {
      setMind(null);
      setMeta({
        source: "empty",
        lastUpdated: new Date().toISOString(),
        endpoint: "/api/memory/hive-mind",
        httpStatus: result.status,
        error: result.error || `HTTP ${result.status}`,
      });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => onHiveNukeComplete(() => {
    setMind(null);
    void load();
  }), [load]);

  const fr = mind?.ai_review_freshness;

  return (
    <section className="space-y-5 mt-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-hive-violet" />
          <h2 className="text-lg font-semibold text-white">Hive Mind</h2>
        </div>
        <label className="flex items-center gap-2 text-[10px] text-slate-400">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived
        </label>
      </header>

      {meta.error && (
        <PanelError title="Hive Mind API failed" meta={meta} expectedShape="{ trading_recent, system_recent, patterns }" />
      )}

      {fr && (
        <div className="flex flex-wrap gap-2 text-[10px]">
          <span className="rounded-full border border-white/10 px-2.5 py-1 text-slate-300">
            AI {fr.freshness ?? "—"}
          </span>
          <span className="rounded-full border border-white/10 px-2.5 py-1 font-mono text-slate-400">
            cycle {fr.latest_cycle_run_id?.slice(0, 8) ?? "—"}
          </span>
        </div>
      )}

      <HiveMemoryGraphPanel compact showArchived={showArchived} categoryFilter="all" />

      <div className="grid md:grid-cols-3 gap-3">
        <GlassPanel title="Trading memories">
          <ul className="text-xs space-y-2 max-h-36 overflow-y-auto scrollbar-thin">
            {(mind?.trading_recent || []).map((l) => (
              <li key={l.title} className="flex gap-2 text-slate-300">
                <Sparkles className="h-3 w-3 text-cyan-400 flex-shrink-0" />
                {l.title}
              </li>
            ))}
          </ul>
        </GlassPanel>
        <GlassPanel title="System issues">
          <ul className="text-xs space-y-2 max-h-36 overflow-y-auto">
            {(mind?.system_recent || []).map((l) => (
              <li key={l.title} className="text-orange-200/85">
                {l.title}
              </li>
            ))}
          </ul>
        </GlassPanel>
        <GlassPanel title="Patterns">
          <ul className="text-xs space-y-1">
            {(mind?.patterns || []).map((p) => (
              <li key={p.title} className="flex justify-between text-slate-400">
                <span className="truncate">{p.title}</span>
                <span className="text-amber-400">×{p.occurrence_count}</span>
              </li>
            ))}
          </ul>
        </GlassPanel>
      </div>
    </section>
  );
}
