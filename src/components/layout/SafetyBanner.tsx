"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";

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
  const [data, setData] = useState<BannerData | null>(null);
  const [degraded, setDegraded] = useState<string | null>(null);

  const load = async () => {
    const lock = await apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire", { timeoutMs: 3000 });
    if (!lock.ok) {
      setDegraded(lock.error || `Live-lock status unavailable (${lock.status})`);
    } else {
      setDegraded(null);
    }
    setData({
      liveTradingLocked: lock.data?.live_lock_status === "locked" || lock.data?.live_trading_enabled !== true,
      paperLearning: "See cockpit",
      currentMode: "watching",
      botCanPlaceOrders: "See cockpit",
      brokerTruth: lock.data?.paper_broker ? "Paper broker" : "Check broker",
      paperBroker: Boolean(lock.data?.paper_broker),
      plainMessage: "Paper-only runtime. The cockpit carries live trade, position, and scanner truth.",
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
  }, []);

  if (!data) return null;

  return (
    <div className="mb-4 rounded-lg border border-cyan-500/20 bg-slate-900/80 px-4 py-3 text-[11px] text-slate-200">
      <div className="flex flex-wrap gap-x-6 gap-y-1 font-medium">
        <span>Live Trading: {data.liveTradingLocked ? "LOCKED" : "CHECK"}</span>
        <span>Paper Learning: {data.paperLearning ?? "See cockpit"}</span>
        <span>Current Mode: {data.currentMode === "watching" ? "Watching" : data.currentMode}</span>
        <span>Bot can place orders now: {data.botCanPlaceOrders ?? "See cockpit"}</span>
        <span>Broker Truth: {data.brokerTruth ?? "-"}</span>
        <span>Paper broker: {data.paperBroker ? "yes" : "no"}</span>
      </div>
      <p className="mt-1 text-slate-400">{data.plainMessage}</p>
      {degraded && <p className="mt-1 text-amber-300/90 text-[10px]">Status degraded: {degraded}</p>}
    </div>
  );
}
