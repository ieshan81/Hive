"use client";

import { useCallback, useEffect, useState } from "react";
import { Gauge, Play, Pause, Square, StepForward, Download, RefreshCw, Lock } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, buildApiUrl, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";

type Dict = Record<string, unknown>;

function num(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function str(v: unknown, fallback = "—"): string {
  if (v === null || v === undefined || v === "") return fallback;
  return String(v);
}

/** One cap usage cell: current vs absolute max, tinted red when the cap is hit. */
function CapCell({ label, used, max }: { label: string; used: number; max: number }) {
  const hit = max > 0 && used >= max;
  const near = max > 0 && used >= max - 1 && !hit;
  const tone = hit
    ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
    : near
      ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
      : "border-white/10 text-slate-200";
  return (
    <div className={`rounded border p-2 ${tone}`}>
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className="font-semibold tabular-nums">
        {used} <span className="text-slate-500">/ {max > 0 ? max : "—"}</span>
      </div>
    </div>
  );
}

export function PaperAutopilotPanel() {
  const [sched, setSched] = useState<Dict | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [canMutate, setCanMutate] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<Dict>("/api/autonomous-paper-learning/scheduler/status");
    if (r.ok && r.data) setSched(r.data);
  }, []);

  useEffect(() => {
    load();
    Promise.all([checkServerOperatorProxy(), Promise.resolve(hasSessionOperatorToken())]).then(
      ([proxy, session]) => setCanMutate(proxy || session)
    );
    const onRefresh = () => load();
    window.addEventListener("hive:paper-learning-refresh", onRefresh);
    return () => window.removeEventListener("hive:paper-learning-refresh", onRefresh);
  }, [load]);

  async function act(path: string, label: string, body?: Dict, confirmMsg?: string) {
    if (!canMutate) {
      setMsg("Operator authorization required — configure server proxy or session token in Settings.");
      return;
    }
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(true);
    const r = await apiPostOperator<Dict>(path, { operator: "ui", ...(body || {}) });
    if (r.ok && r.data) {
      const d = r.data;
      const detail =
        d.stopped_reason !== undefined
          ? `ran ${num(d.ticks_run)} tick(s), stopped: ${str(d.stopped_reason, "none")}`
          : "ok";
      setMsg(`${label}: ${detail}`);
    } else {
      setMsg(`${label}: ${r.error ?? r.status}`);
    }
    await load();
    window.dispatchEvent(new Event("hive:paper-learning-refresh"));
    setBusy(false);
  }

  const enabled = Boolean(sched?.scheduler_enabled);
  const paused = Boolean(sched?.paused);
  const state = paused ? "PAUSED" : enabled ? "ON" : "OFF";
  const stateTone =
    state === "ON"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : state === "PAUSED"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
        : "border-slate-500/30 bg-slate-500/10 text-slate-300";

  const caps = (sched?.absolute_caps as Dict) || {};
  const entryCapHit = Boolean(sched?.entry_cap_hit);
  const reasons = (sched?.entry_cap_hit_reasons as string[]) || [];

  const btn = "rounded border px-3 py-1.5 text-[10px] font-medium disabled:opacity-40";

  return (
    <GlassPanel title="Paper Autopilot" icon={<Gauge className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Always-on paper scheduler (cron POST /tick). Absolute caps below can never be disabled or exceeded and hold even
        in capital-allocator mode. Live trading stays locked.
      </p>

      {/* Status row */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold tracking-wide ${stateTone}`}>
          {state}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-[10px] font-semibold text-rose-300">
          <Lock className="h-3 w-3" /> LIVE LOCKED
        </span>
        <span className="text-[10px] text-slate-500">
          Interval: {num(sched?.interval_seconds)}s · Allocator: {sched?.use_capital_allocator ? "ON" : "OFF"}
        </span>
      </div>

      {/* Absolute caps bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-[10px]">
        <CapCell
          label="Scheduler ticks today"
          used={num(sched?.ticks_today)}
          max={num(sched?.absolute_max_scheduler_ticks_per_day)}
        />
        <CapCell
          label="New entries today"
          used={num(sched?.new_entries_today)}
          max={num(caps.absolute_max_new_entries_per_day)}
        />
        <CapCell
          label="New entries / hour"
          used={num(sched?.new_entries_this_hour)}
          max={num(caps.absolute_max_new_entries_per_hour)}
        />
        <CapCell
          label="Open positions"
          used={num(sched?.open_positions)}
          max={num(caps.absolute_max_open_positions)}
        />
      </div>

      {entryCapHit && (
        <div className="mb-3 rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200">
          Entry cap reached — new paper entries are blocked until the window rolls over.
          {reasons.length > 0 && <> ({reasons.join(", ")})</>}
        </div>
      )}

      {/* Timing row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Last tick (UTC)</div>
          <div className="font-semibold truncate">{str(sched?.last_tick_at)}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Next tick (UTC)</div>
          <div className="font-semibold truncate">{str(sched?.next_planned_at_utc)}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Pause reason</div>
          <div className="font-semibold truncate">{str(sched?.paused_reason, paused ? "paused" : "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Error / reject streak</div>
          <div className="font-semibold tabular-nums">
            {num(sched?.broker_error_streak)} / {num(sched?.rejection_streak)}
          </div>
        </div>
      </div>

      {/* Operator controls (token-gated, paper-only) */}
      <div className="flex flex-wrap gap-2 mb-3 border-t border-white/5 pt-3">
        <button
          type="button"
          disabled={busy || !canMutate}
          className={`${btn} border-cyan-500/50 bg-cyan-600/30 text-cyan-100`}
          onClick={() =>
            act("/api/autonomous-paper-learning/scheduler/enable", "Enable autopilot", undefined, "Enable the always-on paper autopilot?")
          }
        >
          <Play className="inline h-3 w-3 mr-1" />
          Enable
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className={`${btn} border-white/20 text-slate-200`}
          onClick={() => act("/api/autonomous-paper-learning/scheduler/pause", "Pause autopilot")}
        >
          <Pause className="inline h-3 w-3 mr-1" />
          Pause
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className={`${btn} border-white/20 text-slate-200`}
          onClick={() => act("/api/autonomous-paper-learning/supervised-burst", "One supervised tick", { max_ticks: 1 })}
        >
          <StepForward className="inline h-3 w-3 mr-1" />
          Run 1 supervised tick
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className={`${btn} border-white/20 text-slate-200`}
          onClick={() => act("/api/autonomous-paper-learning/supervised-burst", "Supervised burst", { max_ticks: 3 })}
        >
          <StepForward className="inline h-3 w-3 mr-1" />
          Run 3-tick burst
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className={`${btn} border-amber-500/40 text-amber-200`}
          onClick={() => act("/api/autonomous-paper-learning/stop-after-tick", "Stop after current tick")}
        >
          <Square className="inline h-3 w-3 mr-1" />
          Stop after current tick
        </button>
        <a
          href={buildApiUrl("/api/autonomous-paper-learning/export-bundle/download")}
          className={`${btn} border-white/20 text-slate-200 inline-flex items-center no-underline`}
        >
          <Download className="inline h-3 w-3 mr-1" />
          Export bundle
        </a>
        <button type="button" disabled={busy} className={`${btn} border-white/10`} onClick={() => load()}>
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      {msg && <p className="text-[10px] text-slate-400">{msg}</p>}
    </GlassPanel>
  );
}
