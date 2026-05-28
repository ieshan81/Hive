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
  const [degraded, setDegraded] = useState<string | null>(null);

  const load = async () => {
    const [cockpit, lock] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/cockpit", { timeoutMs: 15000 }),
      apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire", { timeoutMs: 8000 }),
    ]);
    if (!cockpit.ok) {
      setDegraded(cockpit.error || `Cockpit unavailable (${cockpit.status})`);
    } else {
      setDegraded(null);
    }
    const ctrl = (cockpit.data?.control as Record<string, unknown>) || {};
    const acct = (cockpit.data?.account as Record<string, unknown>) || {};
    setData({
      liveTradingLocked: lock.data?.live_lock_status === "locked" || cockpit.data?.live_locked !== false,
      paperLearning: ctrl.paper_learning_on ? "ON" : "OFF",
      trainingMode: ctrl.paper_learning_on ? "ON" : "OFF",
      confidenceScore: Number(cockpit.data?.passed_count ?? 0) * 8 + 40,
      confidenceLabel: ctrl.bot_can_place ? "Ready" : "Developing",
      currentMode: String(ctrl.mode || "watching"),
      botCanPlaceOrders: ctrl.bot_can_place ? "YES" : "NO",
      openPositions: Array.isArray(cockpit.data?.positions) ? cockpit.data.positions.length : 0,
      brokerTruth: acct.connected ? "Synced" : "Not connected",
      paperBroker: Boolean(acct.connected),
      plainMessage: String(
        cockpit.data?.ai_cockpit_message ||
          "Live cockpit — paper only, formula cage executes, Gemini advises."
      ),
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
      {degraded && (
        <p className="mt-1 text-amber-300/90 text-[10px]">Status degraded: {degraded}</p>
      )}
    </div>
  );
}
