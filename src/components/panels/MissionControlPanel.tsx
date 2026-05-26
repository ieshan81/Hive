"use client";

import { useCallback, useEffect, useState } from "react";
import { Shield, Activity, Zap, Wallet, AlertTriangle } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";

type MissionStatus = {
  status?: string;
  system_state_banner?: {
    headline?: string;
    subline?: string;
    live_locked?: boolean;
    paper_broker?: boolean;
    degraded?: boolean;
  };
  push_pull_engine?: { market_mode_label?: string; analysis_only?: boolean };
  paper_learning?: { desired_enabled?: boolean; effective_enabled?: boolean; can_place_paper_orders?: boolean };
  scheduler?: { desired_enabled?: boolean; effective_enabled?: boolean; last_tick_at?: string };
  env_pause?: { any_env_pause?: boolean; paper_trading_paused_by_env?: boolean };
  live_lock?: { live_lock_status?: string };
  last_tick_summary?: { plain?: string; tick_at?: string; orders_created?: number };
  capital_allocator?: { status?: string; headline?: string };
  blockers?: string[];
  next_action_plain?: string;
};

export function MissionControlPanel() {
  const [data, setData] = useState<MissionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        <div className="flex flex-wrap gap-2 mt-3">
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Live: {data?.live_lock?.live_lock_status === "locked" ? "Env lock active" : data?.live_lock?.live_lock_status}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Paper orders: {data?.paper_learning?.can_place_paper_orders ? "Allowed" : "Blocked / skipped"}
          </span>
          {envPaused && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-amber-900/50 text-amber-200">Env paused</span>
          )}
        </div>
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
            Desired: {data?.paper_learning?.desired_enabled ? "ON" : "Off (operator setting)"} · Effective:{" "}
            {envPaused
              ? "Blocked by env pause"
              : data?.paper_learning?.effective_enabled
                ? "Learning active"
                : "Off (operator setting)"}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">
            Scheduler:{" "}
            {envPaused
              ? "Blocked by env pause"
              : data?.scheduler?.effective_enabled
                ? "Running"
                : "Off (operator setting)"}
          </p>
        </GlassPanel>

        <GlassPanel title="Last tick" icon={<Activity className="h-4 w-4" />}>
          <p className="text-sm text-white">{data?.last_tick_summary?.plain ?? "No tick yet"}</p>
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
            <AlertTriangle className="h-3.5 w-3.5" /> Blockers / warnings
          </p>
          <ul className="mt-1 text-[11px] text-slate-400 list-disc pl-4">
            {data?.blockers?.map((b) => (
              <li key={b}>{b.replace(/_/g, " ")}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
