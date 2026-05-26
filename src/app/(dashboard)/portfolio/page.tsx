"use client";

import { useCallback, useEffect, useState } from "react";
import { Wallet, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { PanelError } from "@/components/ui/PanelError";
import { apiGet, apiPost } from "@/lib/apiClient";
import {
  normalizeOrders,
  normalizePositions,
} from "@/lib/apiNormalize";
import { OrderMetricsBar } from "@/components/ui/OrderMetricsBar";
import { ExecutionOrdersTable } from "@/components/ui/ExecutionOrdersTable";
import { PortfolioExecutionPanel } from "@/components/panels/PortfolioExecutionPanel";
import type { OrderSummaryCounts } from "@/lib/orderDisplay";
import type { OrderRecord, PanelLoadMeta, Position } from "@/types/api";

export default function PortfolioPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [orderSummary, setOrderSummary] = useState<OrderSummaryCounts | undefined>();
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<Record<string, PanelLoadMeta>>({});

  const load = useCallback(async () => {
    setLoading(true);
    const m: Record<string, PanelLoadMeta> = {};
    const ts = new Date().toISOString();

    const [pRes, oRes, dashRes] = await Promise.all([
      apiGet("/api/positions"),
      apiGet("/api/orders"),
      apiGet("/api/dashboard"),
    ]);

    if (pRes.ok) {
      setPositions(normalizePositions(pRes.data));
      m.positions = { source: "live_api", lastUpdated: ts, endpoint: "/api/positions", httpStatus: pRes.status };
    } else {
      setPositions([]);
      m.positions = {
        source: "empty",
        lastUpdated: ts,
        endpoint: "/api/positions",
        httpStatus: pRes.status,
        error: pRes.error || `HTTP ${pRes.status}`,
      };
    }

    if (dashRes.ok && dashRes.data && typeof dashRes.data === "object") {
      const d = dashRes.data as Record<string, unknown>;
      setOrderSummary(d.orderSummary as OrderSummaryCounts | undefined);
    }

    if (oRes.ok) {
      setOrders(normalizeOrders(oRes.data));
      m.orders = { source: "live_api", lastUpdated: ts, endpoint: "/api/orders", httpStatus: oRes.status };
    } else {
      setOrders([]);
    }

    setMeta(m);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    await apiPost("/api/positions/refresh");
    await load();
  }

  return (
    <section className="max-w-5xl space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet className="h-6 w-6 text-hive-cyan" />
          <h1 className="text-xl font-semibold text-white">Portfolio &amp; Execution</h1>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="flex items-center gap-1 text-xs text-hive-cyan border border-hive-cyan/30 rounded px-3 py-1.5"
        >
          <RefreshCw className="h-3 w-3" /> Refresh broker
        </button>
      </header>

      {loading ? (
        <EmptyState message="Loading broker positions…" />
      ) : (
        <>
          <GlassPanel title="Open positions">
            {meta.positions?.error ? (
              <PanelError title="Positions fetch failed" meta={meta.positions} expectedShape='{ positions: [...] }' />
            ) : positions.length === 0 ? (
              <EmptyState message="No open positions." />
            ) : (
              <div className="space-y-3">
                {positions.map((pos) => (
                  <article key={String(pos.symbol)} className="rounded-lg border border-white/5 bg-white/2 p-3 text-sm">
                    <div className="flex justify-between">
                      <span className="font-semibold text-white">{String(pos.symbol)}</span>
                      <span className="text-emerald-400 text-xs">{String(pos.source ?? "broker")}</span>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Orders">
            <OrderMetricsBar summary={orderSummary} compact />
            {orders.length === 0 ? (
              <EmptyState message="No orders on record." />
            ) : (
              <ExecutionOrdersTable rows={orders as unknown as Record<string, unknown>[]} mode="order" />
            )}
          </GlassPanel>

          <PortfolioExecutionPanel />
        </>
      )}
    </section>
  );
}
