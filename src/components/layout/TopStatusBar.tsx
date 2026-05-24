"use client";

import { useState } from "react";
import { Activity, Brain, Clock, Download, FileText, Shield } from "lucide-react";
import { SystemLogModal } from "@/components/panels/SystemLogModal";
import { getDiagnosticBundleUrl } from "@/lib/dashboard";
import { formatSyncTime } from "@/lib/datetime";
import type { StatusChip, SystemStatus } from "@/types/dashboard";

interface TopStatusBarProps {
  lastSync: string;
  lastSyncAt?: string | null;
  statusChips: StatusChip[];
  systemStatus: SystemStatus;
}

function ChipIcon({ label }: { label: string }) {
  if (label.includes("Market")) return <Activity className="h-3.5 w-3.5" />;
  if (label.includes("AI")) return <Brain className="h-3.5 w-3.5" />;
  if (label.includes("Risk")) return <Shield className="h-3.5 w-3.5" />;
  return <Clock className="h-3.5 w-3.5" />;
}

export function TopStatusBar({ lastSync, lastSyncAt, statusChips, systemStatus }: TopStatusBarProps) {
  const [logOpen, setLogOpen] = useState(false);
  const syncLabel = formatSyncTime(lastSyncAt ?? (lastSync !== "Not synced" ? lastSync : null));

  return (
    <header className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Caged Hive Quant</h1>
        <p className="text-sm text-slate-500 mt-0.5">AI-managed trading under strict survival rules · Paper only</p>
        {!systemStatus.alpacaConnected && (
          <p className="text-xs text-amber-400 mt-1">Not connected — configure Alpaca credentials</p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:gap-3">
        {statusChips.map((chip) => (
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
        <a href={getDiagnosticBundleUrl()} className="flex items-center gap-2 rounded-lg border border-hive-cyan/30 bg-hive-cyan/5 px-3 py-1.5 text-xs font-medium text-hive-cyan transition hover:bg-hive-cyan/10">
          <Download className="h-3.5 w-3.5" />
          Diagnostic Bundle
        </a>
        <button
          type="button"
          onClick={() => setLogOpen(true)}
          className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/3 px-3 py-1.5 text-xs font-medium text-slate-300"
        >
          <FileText className="h-3.5 w-3.5" />
          System Log
        </button>
        <SystemLogModal open={logOpen} onClose={() => setLogOpen(false)} />
      </div>
    </header>
  );
}
