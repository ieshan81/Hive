"use client";

import { useCallback, useEffect, useState } from "react";
import { Shield, Activity, Zap, Wallet, AlertTriangle, Play } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";

type MissionStatus = {
  status?: string;
  fresh_brain?: boolean;
  system_state_banner?: {
    headline?: string;
    subline?: string;
    live_locked?: boolean;
    paper_broker?: boolean;
    degraded?: boolean;
  };
  push_pull_engine?: { market_mode_label?: string; analysis_only?: boolean };
  paper_learning?: {
    desired_enabled?: boolean;
    effective_enabled?: boolean;
    can_place_paper_orders?: boolean;
    paper_learning_on?: string;
    paper_execution_on?: string;
  };
  scheduler?: { desired_enabled?: boolean; effective_enabled?: boolean; last_tick_at?: string };
  env_pause?: { any_env_pause?: boolean; paper_trading_paused_by_env?: boolean };
  live_lock?: { live_lock_status?: string };
  last_tick_summary?: { plain?: string; tick_at?: string; orders_created?: number };
  capital_allocator?: { status?: string; headline?: string };
  blockers?: string[];
  can_place_paper_orders?: boolean;
  primary_blocker_plain?: string;
  operator_action_required?: string;
  show_start_fresh_button?: boolean;
  next_action_plain?: string;
};

export function MissionControlPanel() {
  const [data, setData] = useState<MissionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startMsg, setStartMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiGet<MissionStatus>("/api/mission-control/status");
    if (res.ok && res.data) {
      setData(res.data);
      setError(null);
    } else {
      setError(res.error || `HTTP ${res.status}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => onHiveNukeComplete(() => void load()), [load]);

  const startFresh = async () => {
    setStarting(true);
    setStartMsg(null);
    const proxyOk = await checkServerOperatorProxy();
    if (!proxyOk && !hasSessionOperatorToken()) {
      setStartMsg("Operator token required — set token in Settings.");
      setStarting(false);
      return;
    }
    const res = await apiPostOperator<{ message?: string; status?: string }>(
      "/api/autonomous-paper-learning/start-fresh",
      { operator: "ui" }
    );
    setStarting(false);
    if (res.ok && res.data?.status === "ok") {
      setStartMsg(res.data.message || "Fresh paper learning started.");
      await load();
    } else {
      setStartMsg(res.error || res.data?.message || "Start fresh failed");
    }
  };

  if (loading) return <EmptyState message="Loading Mission Control…" className="min-h-[240px]" />;
  if (error) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-amber-200 text-sm">
        Mission Control unavailable: {error}
      </div>
    );
  }

  const banner = data?.system_state_banner;
  const envPaused = data?.env_pause?.any_env_pause;
  const canPlace = data?.can_place_paper_orders ?? data?.paper_learning?.can_place_paper_orders;

  return (
    <section className="space-y-4 max-w-5xl">
      <div
        className={`rounded-xl border p-5 ${
          envPaused
            ? "border-amber-500/40 bg-amber-500/10"
            : banner?.degraded
              ? "border-amber-500/30 bg-amber-500/5"
              : "border-emerald-500/30 bg-emerald-500/5"
        }`}
      >
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Shield className="h-6 w-6 text-hive-cyan" />
          Mission Control
        </h1>
        <p className="text-lg text-white mt-2">{banner?.headline ?? "System status unknown"}</p>
        <p className="text-sm text-slate-400 mt-1">{banner?.subline ?? data?.next_action_plain}</p>

        {!canPlace && data?.primary_blocker_plain && (
          <p className="text-sm text-amber-200 mt-3 border-t border-white/10 pt-3">
            Paper orders blocked: {data.primary_blocker_plain}
          </p>
        )}
        {canPlace && (
          <p className="text-sm text-emerald-300 mt-3">Bot can place paper orders: YES (under allocator limits)</p>
        )}

        <div className="flex flex-wrap gap-2 mt-3">
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Live: {data?.live_lock?.live_lock_status === "locked" ? "Locked" : data?.live_lock?.live_lock_status}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Paper learning: {data?.paper_learning?.paper_learning_on ?? (data?.paper_learning?.desired_enabled ? "ON" : "OFF")}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Paper execution: {data?.paper_learning?.paper_execution_on ?? "—"}
          </span>
          {data?.fresh_brain && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-900/40 text-cyan-200">Fresh brain</span>
          )}
        </div>

        {data?.show_start_fresh_button && !envPaused && (
          <button
            type="button"
            onClick={() => void startFresh()}
            disabled={starting}
            className="mt-4 flex items-center gap-2 rounded-lg bg-hive-cyan px-4 py-2.5 text-sm font-semibold text-black hover:bg-cyan-300 disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {starting ? "Starting…" : "START FRESH PAPER LEARNING"}
          </button>
        )}
        {startMsg && <p className="text-[11px] text-slate-400 mt-2">{startMsg}</p>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <GlassPanel title="Push-Pull Engine" icon={<Zap className="h-4 w-4" />}>
          <p className="text-sm text-white">{data?.push_pull_engine?.market_mode_label}</p>
          {data?.push_pull_engine?.analysis_only && (
            <p className="text-[11px] text-amber-300 mt-1">Analysis only — no new entries</p>
          )}
        </GlassPanel>

        <GlassPanel title="Paper Learning" icon={<Activity className="h-4 w-4" />}>
          <p className="text-sm text-white">
            Learning: {envPaused ? "Blocked by env pause" : data?.paper_learning?.effective_enabled ? "ON" : "OFF"}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">
            Scheduler:{" "}
            {envPaused ? "Blocked" : data?.scheduler?.effective_enabled ? "ON — automatic ticks" : "OFF"}
          </p>
        </GlassPanel>

        <GlassPanel title="Last tick" icon={<Activity className="h-4 w-4" />}>
          <p className="text-sm text-white">{data?.last_tick_summary?.plain ?? "No scheduler tick completed yet"}</p>
          {data?.last_tick_summary?.tick_at && (
            <p className="text-[10px] text-slate-500 mt-1">{data.last_tick_summary.tick_at}</p>
          )}
        </GlassPanel>

        <GlassPanel title="Capital allocator" icon={<Wallet className="h-4 w-4" />}>
          <p className="text-sm text-white capitalize">{data?.capital_allocator?.status ?? "—"}</p>
          <p className="text-[11px] text-slate-500 mt-1">{data?.capital_allocator?.headline}</p>
        </GlassPanel>
      </div>

      {(data?.blockers?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
          <p className="text-[11px] font-semibold text-amber-300 flex items-center gap-1">
            <AlertTriangle className="h-3.5 w-3.5" /> Status
          </p>
          <ul className="mt-1 text-[11px] text-slate-400 list-disc pl-4">
            {data?.blockers?.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
