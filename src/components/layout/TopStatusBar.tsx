"use client";

import { useEffect, useState } from "react";
import { Activity, Brain, Clock, Download, FileText, Shield } from "lucide-react";
import { SystemLogModal } from "@/components/panels/SystemLogModal";
import { apiGet } from "@/lib/apiClient";
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
  if (label.includes("Stocks") || label.includes("Crypto")) return <Activity className="h-3.5 w-3.5" />;
  if (label.includes("Market")) return <Activity className="h-3.5 w-3.5" />;
  if (label.includes("AI")) return <Brain className="h-3.5 w-3.5" />;
  if (label.includes("Risk")) return <Shield className="h-3.5 w-3.5" />;
  return <Clock className="h-3.5 w-3.5" />;
}

export function TopStatusBar({ lastSync, lastSyncAt, statusChips, systemStatus }: TopStatusBarProps) {
  const [logOpen, setLogOpen] = useState(false);
  const [brokerProof, setBrokerProof] = useState<{
    alpacaConnected?: boolean;
    aiLearning?: boolean;
  }>({});
  const syncLabel = formatSyncTime(lastSyncAt ?? (lastSync !== "Not synced" ? lastSync : null));
  const alpacaConnected = systemStatus.alpacaConnected || Boolean(brokerProof.alpacaConnected);
  const displayedChips = statusChips.map((chip) => {
    if (chip.label === "AI Mode" && brokerProof.aiLearning) {
      return { ...chip, value: "LEARNING", variant: "info" as const };
    }
    return chip;
  });

  useEffect(() => {
    let cancelled = false;
    async function loadBrokerProof() {
      const [apl, lock, advisor] = await Promise.all([
        apiGet<Record<string, unknown>>("/api/autonomous-paper-learning/status", { timeoutMs: 4500 }),
        apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire", { timeoutMs: 2500 }),
        apiGet<Record<string, unknown>>("/api/ai-advisor/status", { timeoutMs: 2500 }),
      ]);
      if (cancelled) return;
      const banner = (apl.data?.safety_banner || {}) as Record<string, unknown>;
      const paperBroker = Boolean(lock.data?.paper_broker ?? banner.paperBroker);
      const brokerSynced =
        banner.brokerTruth === "Synced" ||
        Boolean(apl.data?.broker_truth_synced) ||
        typeof banner.openPositions === "number" ||
        typeof apl.data?.open_paper_positions === "number";
      setBrokerProof({
        alpacaConnected: paperBroker && brokerSynced,
        aiLearning:
          Boolean(advisor.data?.advisor_active) ||
          Boolean(advisor.data?.gemini_configured) ||
          banner.currentMode === "push_pull_paper_learning",
      });
    }
    loadBrokerProof();
    const t = setInterval(loadBrokerProof, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  return (
    <header className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Caged Hive Quant</h1>
        <p className="text-sm text-slate-500 mt-0.5">AI-managed formula paper learning · Live locked</p>
        {!alpacaConnected && (
          <p className="text-xs text-amber-400 mt-1">Not connected — configure Alpaca credentials</p>
        )}
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
