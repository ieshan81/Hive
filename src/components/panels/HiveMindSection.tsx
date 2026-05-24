"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain } from "lucide-react";
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

  return (
    <section className="space-y-4 mt-6">
      <header className="flex items-center gap-2">
        <Brain className="h-5 w-5 text-hive-violet" />
        <h2 className="text-lg font-semibold text-white">Hive Mind</h2>
      </header>

      <GlassPanel title="AI review freshness" className="text-sm">
        <ul className="text-xs text-slate-400 space-y-1">
          <li>
            Latest cycle:{" "}
            <span className="font-mono text-slate-300">{fr?.latest_cycle_run_id?.slice(0, 8) ?? "—"}…</span>
          </li>
          <li>
            Review cycle:{" "}
            <span className="font-mono text-slate-300">{fr?.review_cycle_run_id?.slice(0, 8) ?? "none"}…</span>
          </li>
          <li>
            Freshness:{" "}
            <span
              className={
                fr?.freshness === "latest"
                  ? "text-emerald-400"
                  : fr?.freshness === "stale"
                    ? "text-amber-400"
                    : "text-slate-300"
              }
            >
              {fr?.freshness ?? "unknown"}
            </span>
            {fr?.skip_reason && <span className="text-slate-500"> ({fr.skip_reason})</span>}
          </li>
        </ul>
      </GlassPanel>

      <div className="flex flex-wrap gap-2 text-[10px]">
        <label className="flex items-center gap-1 text-slate-400">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived in graph
        </label>
      </div>

      <HiveMemoryGraphPanel compact showArchived={showArchived} categoryFilter="trading_memory" />

      <div className="grid md:grid-cols-2 gap-4">
        <GlassPanel title="Recent trading memories">
          <ul className="text-xs space-y-2 max-h-40 overflow-y-auto">
            {(mind?.trading_recent || []).map((l) => (
              <li key={l.title} className="text-slate-300 border-b border-white/5 pb-1">
                <span className="text-cyan-400">{l.severity}</span> {l.title}
              </li>
            ))}
          </ul>
        </GlassPanel>
        <GlassPanel title="System issues (audit)">
          <ul className="text-xs space-y-2 max-h-40 overflow-y-auto">
            {(mind?.system_recent || []).map((l) => (
              <li key={l.title} className="text-orange-300/90 border-b border-white/5 pb-1">
                {l.title}
              </li>
            ))}
          </ul>
        </GlassPanel>
      </div>

      <GlassPanel title="Pattern recognition">
        <ul className="text-xs space-y-1">
          {(mind?.patterns || []).map((p) => (
            <li key={p.title} className="text-slate-400">
              {p.title} <span className="text-amber-400">×{p.occurrence_count}</span>
            </li>
          ))}
        </ul>
      </GlassPanel>
    </section>
  );
}
