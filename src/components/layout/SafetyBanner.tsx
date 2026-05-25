"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";

const DEFAULT_PLAIN =
  "The bot found possible paper trades, but Training Mode is OFF — it cannot place orders.";

type BannerData = {
  liveTradingLocked?: boolean;
  trainingMode?: string;
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
        trainingMode: banner?.trainingMode ?? "OFF",
        botCanPlaceOrders: banner?.botCanPlaceOrders ?? "NO",
        openPositions: banner?.openPositions ?? 0,
        brokerTruth: banner?.brokerTruth ?? "—",
        paperBroker: Boolean(lock.data?.paper_broker ?? banner?.paperBroker),
        plainMessage: banner?.plainMessage || DEFAULT_PLAIN,
      });
    })();
  }, []);

  if (!data) return null;

  return (
    <div className="mb-4 rounded-lg border border-cyan-500/20 bg-slate-900/80 px-4 py-3 text-[11px] text-slate-200">
      <div className="flex flex-wrap gap-x-6 gap-y-1 font-medium">
        <span>Live Trading: {data.liveTradingLocked ? "LOCKED" : "CHECK"}</span>
        <span>Training Mode: {data.trainingMode ?? "OFF"}</span>
        <span>Bot can place orders now: {data.botCanPlaceOrders ?? "NO"}</span>
        <span>Open Positions: {data.openPositions ?? 0}</span>
        <span>Broker Truth: {data.brokerTruth ?? "—"}</span>
        <span>Paper broker: {data.paperBroker ? "yes" : "no"}</span>
      </div>
      <p className="mt-1 text-slate-400">{data.plainMessage}</p>
    </div>
  );
}
