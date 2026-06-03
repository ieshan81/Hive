"use client";

import { useEffect, useState } from "react";
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
  const { truth, degraded, loading } = useRuntimeTruth();
  const [data, setData] = useState<BannerData | null>(null);

  useEffect(() => {
    if (!truth) {
      if (!loading) {
        setData({
          liveTradingLocked: true,
          paperLearning: "Loading runtime…",
          currentMode: "Loading",
          botCanPlaceOrders: "Loading",
          brokerTruth: "Loading",
          paperBroker: undefined,
          plainMessage: "Fetching runtime summary…",
        });
      }
      return;
    }
    setData({
      liveTradingLocked: truth.live_locked !== false,
      paperLearning: truth.scheduler_enabled ? "Scheduler ON" : "Scheduler OFF",
      currentMode: truth.paper_candidate_count ? "Evaluating" : "Watching",
      botCanPlaceOrders: truth.paper_entry_ready ? "Paper path ready" : "Waiting for candidate",
      brokerTruth: truth.paper_broker ? "Paper broker" : "Check broker",
      paperBroker: Boolean(truth.paper_broker),
      plainMessage: truth.why_no_trade || "Paper-only runtime. Live trading stays locked.",
    });
  }, [truth, loading]);

  if (!data) return null;

  const paperBrokerLabel =
    data.paperBroker === undefined ? "…" : data.paperBroker ? "yes" : "no";

  return (
    <div className="mb-4 rounded-lg border border-cyan-500/20 bg-slate-900/80 px-4 py-3 text-[11px] text-slate-200">
      <div className="flex flex-wrap gap-x-6 gap-y-1 font-medium">
        <span>Live Trading: {data.liveTradingLocked ? "LOCKED" : "CHECK"}</span>
        <span>Paper Learning: {data.paperLearning ?? "See Mission Control"}</span>
        <span>Current Mode: {data.currentMode === "watching" ? "Watching" : data.currentMode}</span>
        <span>Paper path: {data.botCanPlaceOrders ?? "—"}</span>
        <span>Broker Truth: {data.brokerTruth ?? "-"}</span>
        <span>Paper broker: {paperBrokerLabel}</span>
      </div>
      <p className="mt-1 text-slate-400">{data.plainMessage}</p>
      {degraded || truth?.data_degraded ? (
        <p className="mt-1 text-amber-300/90 text-[10px]">Status degraded — using latest runtime snapshot</p>
      ) : null}
    </div>
  );
}
