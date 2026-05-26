"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

export function AIManagerLearningPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [memories, setMemories] = useState<Record<string, unknown>[]>([]);

  const load = useCallback(async () => {
    const [st, mem] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/ai-manager/status"),
      apiGet<{ memories?: Record<string, unknown>[] }>("/api/ai-manager/memories?limit=20"),
    ]);
    if (st.ok) setStatus(st.data);
    if (mem.ok) setMemories(mem.data?.memories ?? []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onNuke = () => {
      setMemories([]);
      void load();
    };
    window.addEventListener("hive-nuke-complete", onNuke);
    return () => window.removeEventListener("hive-nuke-complete", onNuke);
  }, [load]);

  return (
    <section className="space-y-4">
      <GlassPanel title="AI Manager" icon={<Brain className="h-4 w-4" />}>
        <p className="text-sm text-white">{String(status?.headline ?? "Learning from paper trades")}</p>
        <p className="text-[11px] text-slate-500 mt-1">
          Confidence: {String(status?.confidence_label ?? "—")} ({String(status?.confidence_overall ?? "—")})
        </p>
        <ul className="mt-2 text-[10px] text-slate-600 list-disc pl-4">
          {((status?.questions_answered as string[]) ?? []).map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </GlassPanel>

      <GlassPanel title="Human memory summaries">
        {memories.length === 0 ? (
          <p className="text-sm text-slate-500">
            {String(status?.headline ?? "Fresh brain. No learned memories yet. Paper learning is available.")}
          </p>
        ) : (
          <ul className="space-y-2 max-h-[400px] overflow-y-auto">
            {memories.map((m) => (
              <li key={String(m.id)} className="text-[11px] border-b border-white/5 pb-2">
                <span className="text-white">{String(m.title)}</span>
                <p className="text-slate-400 mt-0.5">{String(m.human_summary)}</p>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </section>
  );
}
