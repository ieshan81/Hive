"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Gauge, Lock } from "lucide-react";
import { apiGet } from "@/lib/apiClient";

type Dict = Record<string, unknown>;

function num(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * Compact, read-only autopilot status chip for the cockpit.
 * Mirrors the authoritative Paper Autopilot panel on /paper-learning and links to it.
 * Never mutates state — pure telemetry from the scheduler status route.
 */
export function CockpitAutopilotChip() {
  const [sched, setSched] = useState<Dict | null>(null);

  const load = useCallback(async () => {
    const r = await apiGet<Dict>("/api/autonomous-paper-learning/scheduler/status", { timeoutMs: 5000 });
    if (r.ok && r.data) setSched(r.data);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    const onRefresh = () => load();
    window.addEventListener("hive:paper-learning-refresh", onRefresh);
    return () => {
      clearInterval(t);
      window.removeEventListener("hive:paper-learning-refresh", onRefresh);
    };
  }, [load]);

  if (!sched) return null;

  const enabled = Boolean(sched.scheduler_enabled);
  const paused = Boolean(sched.paused);
  const state = paused ? "PAUSED" : enabled ? "ON" : "OFF";
  const tone =
    state === "ON"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : state === "PAUSED"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
        : "border-slate-500/30 bg-slate-500/10 text-slate-300";

  const caps = (sched.absolute_caps as Dict) || {};
  const entryCapHit = Boolean(sched.entry_cap_hit);
  const ticksToday = num(sched.ticks_today);
  const maxTicks = num(sched.absolute_max_scheduler_ticks_per_day);
  const entriesToday = num(sched.new_entries_today);
  const maxEntries = num(caps.absolute_max_new_entries_per_day);
  const openPos = num(sched.open_positions);
  const maxOpen = num(caps.absolute_max_open_positions);

  return (
    <Link
      href="/paper-learning"
      className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] no-underline hover:bg-white/5"
    >
      <Gauge className="h-3.5 w-3.5 text-hive-cyan" />
      <span className="font-semibold text-slate-300">Autopilot</span>
      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide ${tone}`}>{state}</span>
      <span className="text-slate-500">
        ticks {ticksToday}/{maxTicks > 0 ? maxTicks : "—"} · entries {entriesToday}/{maxEntries > 0 ? maxEntries : "—"} ·
        open {openPos}/{maxOpen > 0 ? maxOpen : "—"}
      </span>
      {entryCapHit && (
        <span className="rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
          entry cap
        </span>
      )}
      <span className="inline-flex items-center gap-1 text-[10px] text-rose-300/80">
        <Lock className="h-3 w-3" /> live locked
      </span>
    </Link>
  );
}
