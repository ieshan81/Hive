"use client";

import { useEffect, useState } from "react";
import { Lock, Shield } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { fetchRuntimeTruth, type RuntimeTruth } from "@/lib/runtimeTruth";

const DEFAULT_RULES = [
  "Live trading permanently locked in paper-validation mode.",
  "Paper broker only — no real-money order path.",
  "Kill switch and P&L guard may block new entries (not exits).",
  "Alpha scorecard required before paper broker entries.",
  "Stock lane is readiness-only — no stock broker entries.",
];

export function RiskCagePanel() {
  const [truth, setTruth] = useState<RuntimeTruth | null>(null);
  const [paperStatus, setPaperStatus] = useState<Record<string, unknown> | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      fetchRuntimeTruth({ timeoutMs: 6000 }),
      fetch("/api/execution/paper/status").then(async (r) => (r.ok ? r.json() : null)).catch(() => null),
    ]).then(([runtime, paper]) => {
      if (runtime.ok && runtime.data) setTruth(runtime.data);
      if (paper) setPaperStatus(paper);
      else setDetailErr("Detailed cage data temporarily unavailable");
    });
  }, []);

  return (
    <div className="space-y-4">
      <GlassPanel title="Fast safety truth" icon={<Shield className="h-4 w-4" />}>
        <ul className="space-y-1 text-xs text-slate-300">
          <li>Live locked: {truth?.live_locked === false ? "CHECK" : "yes"}</li>
          <li>Broker mode: {truth?.broker_mode ?? "—"} · connected: {truth?.broker_connected ? "yes" : truth?.paper_broker ? "paper configured" : "no"}</li>
          <li>Paper orders enabled: {truth?.paper_orders_enabled ? "yes" : "no"}</li>
          <li>Paper entry path ready: {truth?.paper_entry_ready ? "yes" : "no"}</li>
          <li>Kill switch: {truth?.kill_switch_clear === false ? "active" : "clear"}</li>
          <li>Stock lane: {truth?.stock_lane_mode ?? "—"}</li>
          <li>Scheduler: {truth?.scheduler_enabled ? "ON" : "OFF"}</li>
        </ul>
        {detailErr ? <p className="mt-2 text-[10px] text-amber-300/90">{detailErr} — fast summary above stays valid.</p> : null}
      </GlassPanel>

      <GlassPanel title="Risk Cage" icon={<Lock className="h-4 w-4" />} subtitle="Rules are unbreakable.">
        <ul className="space-y-2 mb-4">
          {DEFAULT_RULES.map((text) => (
            <li
              key={text}
              className="flex items-center justify-between gap-3 rounded-lg border border-white/4 bg-white/2 px-3 py-2"
            >
              <span className="text-xs text-slate-300 flex-1">{text}</span>
              <span className="rounded px-1.5 py-0.5 text-[8px] font-bold tracking-wider bg-hive-cyan/15 text-hive-cyan border border-hive-cyan/25">
                ENFORCED
              </span>
            </li>
          ))}
        </ul>
        {paperStatus?.kill_switch ? (
          <p className="text-[10px] text-slate-500">
            Kill switch state: {String((paperStatus.kill_switch as Record<string, unknown>).state ?? "—")}
          </p>
        ) : null}
        <div className="flex items-center justify-center gap-2 pt-2 border-t border-white/5">
          <Lock className="h-3.5 w-3.5 text-hive-cyan" />
          <p className="text-xs text-hive-cyan/80">The cage protects the mission.</p>
        </div>
      </GlassPanel>
    </div>
  );
}
