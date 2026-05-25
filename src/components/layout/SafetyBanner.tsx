"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";

type BannerData = {
  liveTradingLocked?: boolean;
  paperLearning?: string;
  trainingMode?: string;
  confidenceScore?: number;
  confidenceLabel?: string;
  currentMode?: string;
  botCanPlaceOrders?: string;
  openPositions?: number;
  brokerTruth?: string;
  paperBroker?: boolean;
  plainMessage?: string;
};

export function SafetyBanner() {
  const [data, setData] = useState<BannerData | null>(null);

  useEffect(() => {
    (async () => {
      const [dash, lock] = await Promise.all([
        apiGet<Record<string, unknown>>("/api/dashboard"),
        apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire"),
      ]);
      const banner = (dash.data as { safetyBanner?: BannerData })?.safetyBanner;
      setData({
        liveTradingLocked:
          lock.data?.live_lock_status === "locked" || Boolean(banner?.liveTradingLocked),
        paperLearning: banner?.paperLearning ?? banner?.trainingMode ?? "OFF",
        trainingMode: banner?.trainingMode ?? "OFF",
        confidenceScore: banner?.confidenceScore,
        confidenceLabel: banner?.confidenceLabel,
        currentMode: banner?.currentMode ?? "watching",
        botCanPlaceOrders: banner?.botCanPlaceOrders ?? "NO",
        openPositions: banner?.openPositions ?? 0,
        brokerTruth: banner?.brokerTruth ?? "—",
        paperBroker: Boolean(lock.data?.paper_broker ?? banner?.paperBroker),
        plainMessage:
          banner?.plainMessage ||
          "The bot is watching only. It cannot place paper orders.",
      });
    })();
  }, []);

  if (!data) return null;

  const modeLabel =
    data.currentMode === "paper_learning"
      ? "Paper Learning"
      : data.currentMode === "paused"
        ? "Paused"
        : data.currentMode === "backtesting"
          ? "Backtesting"
          : data.currentMode === "locked"
            ? "Locked"
            : "Watching";

  return (
    <div className="mb-4 rounded-lg border border-cyan-500/20 bg-slate-900/80 px-4 py-3 text-[11px] text-slate-200">
      <div className="flex flex-wrap gap-x-6 gap-y-1 font-medium">
        <span>Live Trading: {data.liveTradingLocked ? "LOCKED" : "CHECK"}</span>
        <span>Paper Learning: {data.paperLearning ?? "OFF"}</span>
        <span>Current Mode: {modeLabel}</span>
        <span>
          Confidence:{" "}
          {data.confidenceScore != null
            ? `${Math.round(data.confidenceScore)} (${data.confidenceLabel || ""})`
            : "—"}
        </span>
        <span>Bot can place orders now: {data.botCanPlaceOrders ?? "NO"}</span>
        <span>Open Positions: {data.openPositions ?? 0}</span>
        <span>Broker Truth: {data.brokerTruth ?? "—"}</span>
        <span>Paper broker: {data.paperBroker ? "yes" : "no"}</span>
      </div>
      <p className="mt-1 text-slate-400">{data.plainMessage}</p>
    </div>
  );
}
