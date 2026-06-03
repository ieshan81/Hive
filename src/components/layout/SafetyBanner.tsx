"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";
import { useRuntimeTruth } from "@/components/layout/RuntimeTruthProvider";

type BannerData = {
  liveTradingLocked?: boolean;
  paperLearning?: string;
  currentMode?: string;
  botCanPlaceOrders?: string;
  brokerTruth?: string;
  paperBroker?: boolean;
  plainMessage?: string;
};

export function SafetyBanner() {
  const { truth, degraded } = useRuntimeTruth();
  const [data, setData] = useState<BannerData | null>(null);

  const load = async () => {
    if (truth) {
      setData({
        liveTradingLocked: truth.live_locked !== false,
        paperLearning: truth.scheduler_enabled ? "Scheduler ON" : "Scheduler OFF",
        currentMode: truth.paper_candidate_count ? "Evaluating" : "Watching",
        botCanPlaceOrders: truth.paper_entry_ready ? "Paper path ready" : "Waiting for candidate",
        brokerTruth: truth.paper_broker ? "Paper broker" : "Check broker",
        paperBroker: Boolean(truth.paper_broker),
        plainMessage: truth.why_no_trade || "Paper-only runtime. Live trading stays locked.",
      });
      return;
    }
    const lock = await apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire", { timeoutMs: 3000 });
    setData({
      liveTradingLocked: lock.data?.live_lock_status === "locked" || lock.data?.live_trading_enabled !== true,
      paperLearning: "See Mission Control",
      currentMode: "watching",
      botCanPlaceOrders: "See Mission Control",
      brokerTruth: lock.data?.paper_broker ? "Paper broker" : "Check broker",
      paperBroker: Boolean(lock.data?.paper_broker),
      plainMessage: "Paper-only runtime.",
    });
  };

  useEffect(() => {
    load();
    const onRefresh = () => load();
    window.addEventListener("hive:paper-learning-refresh", onRefresh);
    window.addEventListener("hive:cockpit-refresh", onRefresh);
    return () => {
      window.removeEventListener("hive:paper-learning-refresh", onRefresh);
      window.removeEventListener("hive:cockpit-refresh", onRefresh);
    };
  }, [truth]);

  if (!data) return null;

  return (
    <div className="mb-4 rounded-lg border border-cyan-500/20 bg-slate-900/80 px-4 py-3 text-[11px] text-slate-200">
      <div className="flex flex-wrap gap-x-6 gap-y-1 font-medium">
        <span>Live Trading: {data.liveTradingLocked ? "LOCKED" : "CHECK"}</span>
        <span>Paper Learning: {data.paperLearning ?? "See Mission Control"}</span>
        <span>Current Mode: {data.currentMode === "watching" ? "Watching" : data.currentMode}</span>
        <span>Paper path: {data.botCanPlaceOrders ?? "—"}</span>
        <span>Broker Truth: {data.brokerTruth ?? "-"}</span>
        <span>Paper broker: {data.paperBroker ? "yes" : "no"}</span>
      </div>
      <p className="mt-1 text-slate-400">{data.plainMessage}</p>
      {degraded || truth?.data_degraded ? (
        <p className="mt-1 text-amber-300/90 text-[10px]">Status degraded — using latest runtime snapshot</p>
      ) : null}
    </div>
  );
}
