"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, Trash2 } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type LessonRow = {
  lesson_id?: number;
  node_id?: string;
  title: string;
  category?: string;
  status?: string;
  memory_type?: string;
  visible_to_ai?: boolean;
};

export function CleanMindPanel() {
  const [lessons, setLessons] = useState<LessonRow[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [category, setCategory] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "100", include_archived: statusFilter !== "active" ? "true" : "false" });
    if (category) params.set("category", category);
    const r = await apiGet<{ lessons?: LessonRow[] }>(`/api/memory/lessons?${params}`);
    setLessons(r.data?.lessons || []);
    setLoading(false);
  }, [category, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function bulk(path: string, body: Record<string, unknown> = {}) {
    const ids = [...selected];
    if (!ids.length) return;
    await apiPostOperator(`/api/memory/bulk/${path}`, { lesson_ids: ids, ...body });
    setSelected(new Set());
    await load();
  }

  return (
    <GlassPanel title="Clean Mind" icon={<Brain className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Bulk manage memories. Default graph shows active trading memories only; system bugs stay in audit.
      </p>
      <div className="flex flex-wrap gap-2 text-[10px] mb-3">
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="bg-slate-800 border border-white/10 rounded px-2 py-1"
        >
          <option value="">All categories</option>
          <option value="trading_memory">Trading</option>
          <option value="system_issue">System issue</option>
          <option value="backtest_memory">Backtest</option>
          <option value="strategy_research_memory">Research</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-slate-800 border border-white/10 rounded px-2 py-1"
        >
          <option value="active">Active</option>
          <option value="archived">Include archived</option>
        </select>
      </div>
      <div className="flex flex-wrap gap-1 mb-3">
        <button type="button" onClick={() => bulk("archive")} className="px-2 py-1 rounded bg-slate-700 text-[10px]">
          Bulk archive
        </button>
        <button type="button" onClick={() => bulk("hide-from-ai")} className="px-2 py-1 rounded bg-slate-700 text-[10px]">
          Hide from AI
        </button>
        <button
          type="button"
          onClick={() => bulk("set-category", { category: "system_issue" })}
          className="px-2 py-1 rounded bg-orange-900/40 text-[10px] text-orange-200"
        >
          Mark system issue
        </button>
        <button type="button" onClick={() => bulk("restore")} className="px-2 py-1 rounded border border-white/10 text-[10px]">
          Restore
        </button>
        <button
          type="button"
          onClick={() => bulk("delete", { reason: "bulk clean mind" })}
          className="px-2 py-1 rounded bg-red-900/50 text-[10px] flex items-center gap-1"
        >
          <Trash2 className="h-3 w-3" /> Delete selected
        </button>
      </div>
      {loading ? (
        <p className="text-xs text-slate-500">Loading…</p>
      ) : (
        <ul className="text-xs max-h-64 overflow-y-auto space-y-1">
          {lessons.map((l) => {
            const id = l.lesson_id ?? parseInt(String(l.node_id || "").replace("lesson-", ""), 10);
            if (!id) return null;
            return (
              <li key={id} className="flex items-start gap-2 border-b border-white/5 py-1">
                <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)} />
                <div>
                  <span className="text-white">{l.title}</span>
                  <span className="text-slate-600 ml-2">
                    {l.category} · {l.status}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </GlassPanel>
  );
}
