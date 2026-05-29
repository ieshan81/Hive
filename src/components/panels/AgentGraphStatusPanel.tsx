"use client";

import { useCallback, useEffect, useState } from "react";
import { GitBranch, Play } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type ResearchStatus = {
  agent_loop_status?: Record<string, unknown>;
};

type AgentRuns = {
  runs?: Record<string, unknown>[];
};

export function AgentGraphStatusPanel() {
  const [status, setStatus] = useState<ResearchStatus | null>(null);
  const [runs, setRuns] = useState<Record<string, unknown>[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [st, runRows] = await Promise.all([
      apiGet<ResearchStatus>("/api/research/status"),
      apiGet<AgentRuns>("/api/research/agent-runs"),
    ]);
    if (st.ok) setStatus(st.data);
    if (runRows.ok) setRuns(runRows.data?.runs || []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runDry() {
    setBusy(true);
    const r = await apiPostOperator("/api/research/agent-loop/run-dry", { actor: "operator" });
    setMsg(r.ok ? "Dry research graph completed. No orders or live flags changed." : r.error || String(r.status));
    await load();
    setBusy(false);
  }

  const loop = status?.agent_loop_status || {};

  return (
    <GlassPanel title="Agent Graph" icon={<GitBranch className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Research agents write auditable state. They cannot submit orders, approve promotion, or change live flags.
      </p>
      <div className="grid grid-cols-3 gap-2 text-[10px] mb-3">
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Agent</p>
          <p className="text-slate-200">{String(loop.latest_agent ?? "not run")}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Node</p>
          <p className="text-slate-200">{String(loop.latest_node ?? "-")}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Status</p>
          <p className="text-emerald-300">{String(loop.latest_status ?? "idle")}</p>
        </div>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={runDry}
        className="inline-flex items-center gap-1 rounded border border-hive-cyan/30 px-2 py-1 text-[10px] text-hive-cyan disabled:opacity-50"
      >
        <Play className="h-3 w-3" /> Run dry graph
      </button>
      {msg ? <p className="mt-2 text-[10px] text-slate-400">{msg}</p> : null}
      <ul className="mt-3 max-h-36 space-y-1 overflow-auto text-[10px] text-slate-400">
        {runs.slice(0, 8).map((r, i) => (
          <li key={`${String(r.graph_run_id)}-${i}`} className="border-t border-white/5 pt-1">
            {String(r.node_name)} - {String(r.status)}
          </li>
        ))}
        {!runs.length ? <li>No graph runs yet.</li> : null}
      </ul>
    </GlassPanel>
  );
}
