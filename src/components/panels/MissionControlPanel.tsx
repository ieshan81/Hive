"use client";

import type { DashboardData } from "@/types/dashboard";

type OrderSummary = {
  orders_attempted?: number;
  orders_sent_to_broker?: number;
  orders_filled?: number;
  orders_rejected?: number;
  orders_blocked_preflight?: number;
  last_order_user_message?: string;
};

type SafetyBanner = {
  liveTradingLocked?: boolean;
  paperLearning?: string;
  trainingMode?: string;
  confidenceScore?: number;
  confidenceLabel?: string;
  currentMode?: string;
  botCanPlaceOrders?: string;
  openPositions?: number;
  brokerTruth?: string;
  plainMessage?: string;
};

export function MissionControlPanel({
  data,
}: {
  data: DashboardData & { safetyBanner?: SafetyBanner; orderSummary?: OrderSummary };
}) {
  const sb = data.safetyBanner;
  const os = data.orderSummary;
  const paperOff = (sb?.paperLearning ?? sb?.trainingMode) === "OFF";
  const trainingOff = paperOff || sb?.botCanPlaceOrders === "NO";
  const botStatus = trainingOff ? "PAUSED" : sb?.botCanPlaceOrders === "YES" ? "READY" : "WATCHING";
  const modeLabel =
    sb?.currentMode === "paper_learning"
      ? "Paper Learning"
      : sb?.currentMode === "paused"
        ? "Paused"
        : "Watching";

  const cards = [
    { title: "Safety status", value: sb?.liveTradingLocked ? "Live locked" : "Check live lock", sub: "Paper training only" },
    { title: "Mode", value: modeLabel, sub: `Paper learning ${sb?.paperLearning ?? sb?.trainingMode ?? "OFF"}` },
    {
      title: "Confidence",
      value: sb?.confidenceScore != null ? String(Math.round(sb.confidenceScore)) : "—",
      sub: sb?.confidenceLabel || "Evidence only — not live permission",
    },
    { title: "Bot status", value: botStatus, sub: sb?.plainMessage || "—" },
    { title: "Broker truth", value: sb?.brokerTruth || "—", sub: "Synced with Alpaca paper" },
    { title: "Open positions", value: String(sb?.openPositions ?? 0), sub: "Broker-confirmed only" },
    {
      title: "Orders (lifetime)",
      value: `Attempted ${os?.orders_attempted ?? 0}`,
      sub: `Filled ${os?.orders_filled ?? 0} · Rejected ${os?.orders_rejected ?? 0} · Sent ${os?.orders_sent_to_broker ?? 0}`,
    },
    {
      title: "Safe next action",
      value: trainingOff ? "Enable training when ready" : "Run once (operator only)",
      sub: os?.last_order_user_message || "No orders yet",
    },
  ];

  return (
    <section className="mb-4 rounded-xl border border-cyan-500/15 bg-slate-900/60 p-4">
      <h2 className="text-sm font-semibold text-white mb-1">Mission control</h2>
      {trainingOff && (
        <p className="text-[11px] text-amber-300/95 mb-3">
          The bot cannot place new paper orders because Training Mode is OFF.
        </p>
      )}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {cards.map((c) => (
          <div key={c.title} className="rounded-lg border border-white/10 bg-black/20 p-3">
            <div className="text-[10px] text-slate-500">{c.title}</div>
            <div className="text-sm font-semibold text-slate-100">{c.value}</div>
            <div className="text-[9px] text-slate-500 mt-1">{c.sub}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
