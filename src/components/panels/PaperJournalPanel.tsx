"use client";

import { useCallback, useEffect, useState } from "react";
import { ScrollText, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type Dict = Record<string, unknown>;

type JournalEntry = {
  ts?: string;
  status?: string;
  reason?: string | null;
  orders_created?: number;
  rejected_this_tick?: number;
  paused?: boolean;
  paused_reason?: string | null;
  supervised?: boolean;
  plain_summary?: string | null;
};

function statusTone(status?: string): string {
  if (status === "ok") return "text-emerald-300";
  if (status === "noop" || status === "skipped") return "text-slate-400";
  if (status === "stopped") return "text-amber-300";
  return "text-slate-300";
}

export function PaperJournalPanel() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [diag, setDiag] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [j, d] = await Promise.all([
      apiGet<Dict>("/api/autonomous-paper-learning/journal?limit=30"),
      apiGet<Dict>("/api/autonomous-paper-learning/diagnostics?days=14"),
    ]);
    if (j.ok && j.data) setEntries((j.data.entries as JournalEntry[]) || []);
    if (d.ok && d.data) setDiag(d.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const onRefresh = () => load();
    window.addEventListener("hive:paper-learning-refresh", onRefresh);
    return () => window.removeEventListener("hive:paper-learning-refresh", onRefresh);
  }, [load]);

  const totals = (diag?.totals as Dict) || {};

  return (
    <GlassPanel title="Paper Run Journal" icon={<ScrollText className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Per-tick journal + {String(diag?.window_days ?? 14)}-day diagnostics (read-only paper telemetry). Newest first.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Ticks (window)</div>
          <div className="font-semibold tabular-nums">{Number(totals.ticks ?? 0)}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Orders created</div>
          <div className="font-semibold tabular-nums">{Number(totals.orders_created ?? 0)}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Rejected</div>
          <div className="font-semibold tabular-nums">{Number(totals.rejected ?? 0)}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Pauses</div>
          <div className="font-semibold tabular-nums">{Number(totals.pauses ?? 0)}</div>
        </div>
      </div>

      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-slate-500">{entries.length} recent tick(s)</span>
        <button
          type="button"
          disabled={loading}
          className="rounded border border-white/10 px-2 py-1 text-[10px] disabled:opacity-40"
          onClick={() => load()}
        >
          <RefreshCw className="inline h-3 w-3" />
        </button>
      </div>

      {entries.length === 0 ? (
        <p className="text-[10px] text-slate-500">No journal entries yet — the autopilot has not ticked.</p>
      ) : (
        <ul className="space-y-1 max-h-64 overflow-y-auto text-[10px]">
          {entries.map((e, i) => (
            <li key={`${e.ts}-${i}`} className="rounded border border-white/5 px-2 py-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 truncate">{e.ts || "—"}</span>
                <span className={`font-semibold ${statusTone(e.status)}`}>
                  {e.supervised ? "supervised " : ""}
                  {e.status || "—"}
                </span>
              </div>
              <div className="text-slate-400">
                orders {Number(e.orders_created ?? 0)} · rejected {Number(e.rejected_this_tick ?? 0)}
                {e.paused ? ` · paused (${e.paused_reason || "?"})` : ""}
                {e.reason ? ` · ${e.reason}` : ""}
              </div>
              {e.plain_summary && <div className="text-slate-500 truncate">{e.plain_summary}</div>}
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
