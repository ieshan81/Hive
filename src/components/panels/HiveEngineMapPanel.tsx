"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Workflow, ShieldCheck } from "lucide-react";
import { apiGet } from "@/lib/apiClient";
import { fetchRuntimeTruth, type RuntimeTruth } from "@/lib/runtimeTruth";

type Node = {
  key: string;
  label: string;
  status: string;
  source_endpoint?: string;
  service?: string;
  latest_evidence_id?: unknown;
  last_error?: string | null;
  blockers?: string[];
  can_mutate?: boolean;
  operator_required?: boolean;
  live_path?: boolean;
};

type EngineMap = {
  status: string;
  generated_at?: string;
  orders_authority?: string;
  paper_live_separation?: {
    real_money_locked?: boolean;
    live_disabled?: boolean;
    standard_paper_entries?: string;
    paper_exploration?: string;
    exits?: string;
  };
  nodes?: Node[];
  latest_trade_lifecycle?: {
    symbol?: string;
    realized_pnl?: number | null;
    realized_pnl_pct?: number | null;
    exit_reason?: string;
    outcome_status?: string;
    memory_lesson_status?: string;
  } | null;
  counts?: Record<string, number>;
};

const STATUS_COLOR: Record<string, string> = {
  ok: "#00FF66", connected: "#00FF66", active: "#00FF66", armed: "#00dbe9",
  flat: "#00dbe9", gated: "#F59E0B", idle: "#849495", open: "#F59E0B",
  unknown: "#849495", blocked: "#EF4444",
};

function dot(status: string) {
  return STATUS_COLOR[status] ?? "#849495";
}

export function HiveEngineMapPanel() {
  const [data, setData] = useState<EngineMap | null>(null);
  const [runtime, setRuntime] = useState<RuntimeTruth | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<Node | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [r, rt] = await Promise.all([
      apiGet<EngineMap>("/api/hive-engine-map", { timeoutMs: 8000 }),
      fetchRuntimeTruth({ timeoutMs: 5000 }),
    ]);
    if (rt.ok && rt.data) setRuntime(rt.data);
    if (r.ok && r.data) {
      setData(r.data);
      setErr(null);
    } else {
      setErr(r.error || "Engine map detail temporarily unavailable");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const sep = data?.paper_live_separation ?? {};
  const lifecycleChips = [
    ["Real Money", sep.real_money_locked === false ? "UNLOCKED" : "LOCKED", sep.real_money_locked !== false ? "#FB7185" : "#EF4444"],
    ["Standard Paper Entries", sep.standard_paper_entries ?? "—", sep.standard_paper_entries === "ALLOWED" ? "#00FF66" : "#F59E0B"],
    ["Paper Exploration", sep.paper_exploration ?? "—", sep.paper_exploration === "ALLOWED" ? "#00FF66" : "#F59E0B"],
    ["Exits", sep.exits ?? "—", sep.exits === "ACTIVE" ? "#00FF66" : "#EF4444"],
    ["Live Trading", sep.live_disabled === false ? "ENABLED" : "DISABLED", "#FB7185"],
  ] as const;

  return (
    <div className="space-y-4 w-full max-w-[1500px] mx-auto px-1 sm:px-2">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Workflow className="h-7 w-7 text-hive-cyan" /> Hive Engine Map
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Read-only view of the whole engine: Universe → Signal → Cage → Broker → Exit → Outcome → Memory → Promotion. No orders, no mutation.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-white/10 text-slate-300 hover:bg-white/5"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </header>

      {err && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
          Detailed engine map: {err}
          {runtime ? (
            <p className="mt-1 text-slate-300">
              Fast lifecycle truth — scheduler {runtime.scheduler_enabled ? "ON" : "OFF"} · paper broker{" "}
              {runtime.paper_broker ? "yes" : "no"} · live locked · last tick {runtime.last_tick_at?.slice(0, 19) ?? "—"}
            </p>
          ) : null}
        </div>
      )}

      {/* Paper / live separation */}
      <div className="grid gap-2 grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
        {lifecycleChips.map(([label, val, color]) => (
          <div key={label} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase text-slate-500">{label}</p>
            <p className="text-base font-bold mono-metric" style={{ color }}>{val}</p>
          </div>
        ))}
      </div>

      {/* Lifecycle nodes */}
      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-3 flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-hive-cyan" /> Trading lifecycle · orders authority: {data?.orders_authority ?? "—"}
        </p>
        <div className="flex flex-wrap items-stretch gap-2">
          {(data?.nodes ?? []).map((n, i) => (
            <button
              key={n.key}
              type="button"
              onClick={() => setSelected(n)}
              className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-left hover:bg-white/[0.06] transition"
              title={n.service}
            >
              <span className="h-2 w-2 rounded-full" style={{ background: dot(n.status), boxShadow: `0 0 6px ${dot(n.status)}` }} />
              <span className="text-xs text-slate-200">{n.label}</span>
              <span className="text-[10px] uppercase" style={{ color: dot(n.status) }}>{n.status}</span>
              {n.blockers && n.blockers.length > 0 && <span className="text-[10px] text-amber-400">!</span>}
              {i < (data?.nodes?.length ?? 0) - 1 && <span className="text-slate-600 ml-1">→</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Selected node detail */}
      {selected && (
        <div className="rounded-xl border border-hive-cyan/30 bg-hive-cyan/[0.04] p-4 text-sm">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-white">{selected.label}
              <span className="ml-2 text-[11px] uppercase" style={{ color: dot(selected.status) }}>{selected.status}</span>
            </p>
            <button onClick={() => setSelected(null)} className="text-xs text-slate-400 hover:text-white">close</button>
          </div>
          <div className="mt-2 grid gap-1 text-[12px] text-slate-300 md:grid-cols-2">
            <p><span className="text-slate-500">Service:</span> {selected.service ?? "—"}</p>
            <p><span className="text-slate-500">Endpoint:</span> {selected.source_endpoint ?? "—"}</p>
            <p><span className="text-slate-500">Latest evidence:</span> {String(selected.latest_evidence_id ?? "—")}</p>
            <p><span className="text-slate-500">Operator token:</span> {selected.operator_required ? "required" : "no"}</p>
            <p><span className="text-slate-500">Can mutate:</span> {selected.can_mutate ? "yes" : "no"}</p>
            <p><span className="text-slate-500">Live path:</span> <span className={selected.live_path ? "text-rose-400" : "text-emerald-400"}>{selected.live_path ? "YES" : "none"}</span></p>
          </div>
          {selected.blockers && selected.blockers.length > 0 && (
            <p className="mt-2 text-[12px] text-amber-300">Blockers: {selected.blockers.join(", ")}</p>
          )}
          {selected.last_error && <p className="mt-1 text-[12px] text-rose-300">Last error: {selected.last_error}</p>}
        </div>
      )}

      {/* Latest completed trade lifecycle */}
      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 text-sm">
        <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">Latest completed trade</p>
        {data?.latest_trade_lifecycle?.symbol ? (
          <p className="text-slate-200">
            <span className="text-hive-cyan font-semibold">{data.latest_trade_lifecycle.symbol}</span>{" "}
            · realized P/L{" "}
            <span className={Number(data.latest_trade_lifecycle.realized_pnl) >= 0 ? "text-emerald-300" : "text-rose-300"}>
              {data.latest_trade_lifecycle.realized_pnl ?? "—"}
            </span>{" "}
            · exit: {data.latest_trade_lifecycle.exit_reason ?? "—"} · outcome: {data.latest_trade_lifecycle.outcome_status} · memory: {data.latest_trade_lifecycle.memory_lesson_status}
          </p>
        ) : (
          <p className="text-slate-400">No completed trade yet.</p>
        )}
        <p className="mt-1 text-[10px] text-slate-500">Real money stays locked. This view never submits an order or changes config.</p>
      </div>
    </div>
  );
}
