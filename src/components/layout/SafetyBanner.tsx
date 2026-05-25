"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";
import { friendlyClassification } from "@/lib/labels";

type BannerData = {
  liveTradingLocked?: boolean;
  trainingMode?: string;
  botCanPlaceOrders?: string;
  openPositions?: number;
  brokerTruth?: string;
  paperBroker?: boolean;
  plainMessage?: string;
  brokerReconciliation?: string;
};

export function SafetyBanner() {
  const [data, setData] = useState<BannerData | null>(null);

  useEffect(() => {
    (async () => {
      const [dash, ft, lock] = await Promise.all([
        apiGet<Record<string, unknown>>("/api/dashboard"),
        apiGet<Record<string, unknown>>("/api/fast-training/status"),
        apiGet<Record<string, unknown>>("/api/settings/live-lock-tripwire"),
      ]);
      const banner = (dash.data as { safetyBanner?: BannerData })?.safetyBanner;
      const br = ft.data?.broker_reconciliation as Record<string, unknown> | undefined;
      setData({
        ...banner,
        liveTradingLocked: lock.data?.live_lock_status === "locked",
        paperBroker: Boolean(lock.data?.paper_broker),
        brokerReconciliation: br?.classification
          ? friendlyClassification(String(br.classification))
          : undefined,
        plainMessage:
          String(ft.data?.plain_message || banner?.plainMessage || "") ||
          "The bot cannot place new paper orders until Training Mode is enabled.",
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
      {data.brokerReconciliation && (
        <p className="mt-1 text-amber-400/90">{data.brokerReconciliation}</p>
      )}
      <p className="mt-1 text-slate-400">{data.plainMessage}</p>
    </div>
  );
}
