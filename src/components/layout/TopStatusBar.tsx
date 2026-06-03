"use client";

import { useEffect, useState } from "react";
import { Activity, Brain, Clock, Shield } from "lucide-react";
import { apiGet } from "@/lib/apiClient";
import { formatSyncTime } from "@/lib/datetime";
import { brokerLabel, showNotConnectedWarning, type RuntimeTruth } from "@/lib/runtimeTruth";
import { useRuntimeTruth } from "@/components/layout/RuntimeTruthProvider";
import type { StatusChip, SystemStatus } from "@/types/dashboard";

interface TopStatusBarProps {
  lastSync: string;
  lastSyncAt?: string | null;
  statusChips: StatusChip[];
  systemStatus: SystemStatus;
}

function ChipIcon({ label }: { label: string }) {
  if (label.includes("Stocks") || label.includes("Crypto")) return <Activity className="h-3.5 w-3.5" />;
  if (label.includes("Market")) return <Activity className="h-3.5 w-3.5" />;
  if (label.includes("AI") || label.includes("Scheduler")) return <Brain className="h-3.5 w-3.5" />;
  if (label.includes("Risk")) return <Shield className="h-3.5 w-3.5" />;
  return <Clock className="h-3.5 w-3.5" />;
}

export function TopStatusBar({ lastSync, lastSyncAt, statusChips, systemStatus }: TopStatusBarProps) {
  const { truth, degraded } = useRuntimeTruth();
  const [aiLearning, setAiLearning] = useState(false);
  const runtime = truth as RuntimeTruth | null;
  const syncLabel = formatSyncTime(
    lastSyncAt ?? runtime?.account_last_sync_at ?? runtime?.last_tick_at ?? runtime?.generated_at ??
      (lastSync !== "Not synced" ? lastSync : null)
  );
  const brokerOk = Boolean(runtime?.broker_connected || (runtime?.paper_broker && runtime?.paper_orders_enabled));
  const showNotConnected = showNotConnectedWarning(runtime) && !brokerOk && !systemStatus.paperBroker;

  const displayedChips = statusChips.map((chip) => {
    if (chip.label === "Scheduler" && runtime?.scheduler_enabled != null) {
      return {
        ...chip,
        value: runtime.scheduler_enabled ? "ON" : "OFF",
        variant: runtime.scheduler_enabled ? ("success" as const) : ("neutral" as const),
      };
    }
    if (chip.label === "AI Mode" && aiLearning) {
      return { ...chip, value: "LEARNING", variant: "info" as const };
    }
    return chip;
  });

  useEffect(() => {
    let cancelled = false;
    apiGet<Record<string, unknown>>("/api/ai-advisor/status", { timeoutMs: 4000 }).then((advisor) => {
      if (cancelled) return;
      setAiLearning(Boolean(advisor.data?.advisor_active) || Boolean(advisor.data?.gemini_configured));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Caged Hive Quant</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          AI-managed formula paper learning · {runtime?.live_locked === false ? "Live check" : "Live locked"}
        </p>
        {degraded || runtime?.data_degraded ? (
          <p className="text-xs text-amber-300/90 mt-1">Status degraded — using latest runtime snapshot</p>
        ) : showNotConnected ? (
          <p className="text-xs text-amber-400 mt-1">Broker sync pending — paper runtime may still be OK</p>
        ) : runtime?.paper_broker ? (
          <p className="text-xs text-emerald-400/90 mt-1">
            {brokerLabel(runtime, degraded)} · paper mode · scheduler {runtime.scheduler_enabled ? "ON" : "OFF"}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:gap-3">
        {displayedChips.map((chip) => (
          <div key={chip.label} className="flex items-center gap-2 rounded-full border border-white/8 bg-white/3 px-3 py-1.5 text-xs">
            <span className="text-slate-500">{chip.label}</span>
            <span className="flex items-center gap-1.5 font-semibold text-white">
              {chip.variant === "success" && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse-dot" />}
              <ChipIcon label={chip.label} />
              {chip.value}
            </span>
          </div>
        ))}
        <div className="flex items-center gap-2 rounded-full border border-white/8 bg-white/3 px-3 py-1.5 text-xs">
          <Clock className="h-3.5 w-3.5 text-slate-500" />
          <span className="text-slate-500">Last Sync</span>
          <span className="font-medium text-slate-300">{syncLabel}</span>
        </div>
      </div>
    </header>
  );
}
