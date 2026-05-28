"use client";

import { useCallback, useEffect, useState } from "react";
import { Wallet, RefreshCw, AlertTriangle } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { PanelError } from "@/components/ui/PanelError";
import { apiGet, apiPost, apiPostOperator } from "@/lib/apiClient";
import { normalizeOrders, normalizePositions } from "@/lib/apiNormalize";
import { OrderMetricsBar } from "@/components/ui/OrderMetricsBar";
import { ExecutionOrdersTable } from "@/components/ui/ExecutionOrdersTable";
import { PortfolioExecutionPanel } from "@/components/panels/PortfolioExecutionPanel";
import type { OrderSummaryCounts } from "@/lib/orderDisplay";
import type { OrderRecord, PanelLoadMeta, Position } from "@/types/api";

type BrokerRow = {
  symbol?: string;
  qty?: number;
  avg_entry?: number;
  current_price?: number;
  market_value?: number;
  unrealized_pl?: number;
  unrealized_pl_pct?: number;
  synced_at?: string;
  local_history_incomplete?: boolean;
  local_orders?: Record<string, unknown>[];
  local_execution_logs?: Record<string, unknown>[];
};

export default function PortfolioPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [orderSummary, setOrderSummary] = useState<OrderSummaryCounts | undefined>();
  const [recon, setRecon] = useState<Record<string, unknown> | null>(null);
  const [nextAction, setNextAction] = useState<string | null>(null);
  const [exitStatus, setExitStatus] = useState<Record<string, string>>({});
  const [armedExitSymbol, setArmedExitSymbol] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<Record<string, PanelLoadMeta>>({});

  const load = useCallback(async () => {
    setLoading(true);
    const m: Record<string, PanelLoadMeta> = {};
    const ts = new Date().toISOString();

    const psRes = await apiGet<Record<string, unknown>>("/api/page-state/portfolio");
    const pRes = psRes.ok ? psRes : await apiGet("/api/positions");
    const oRes = psRes.ok
      ? ({ ok: true, data: { orders: psRes.data?.orders }, status: 200, error: null } as const)
      : await apiGet("/api/orders");
    const reconRes = psRes.ok
      ? ({ ok: true, data: psRes.data?.reconciliation, status: 200, error: null } as const)
      : await apiGet("/api/portfolio/reconciliation");
    const dashRes = await apiGet("/api/dashboard");

    if (pRes.ok) {
      const posPayload = psRes.ok ? { positions: psRes.data?.positions } : pRes.data;
      setPositions(normalizePositions(posPayload));
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

    if (reconRes.ok) setRecon(reconRes.data as Record<string, unknown>);
    else setRecon(null);
    if (psRes.ok && psRes.data) {
      setNextAction(String(psRes.data.next_action ?? psRes.data.message ?? ""));
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

  async function requestPaperSell(symbol: string) {
    if (armedExitSymbol !== symbol) {
      setArmedExitSymbol(symbol);
      setExitStatus((s) => ({
        ...s,
        [symbol]: "Click Confirm Paper Sell to submit through the paper preflight.",
      }));
      return;
    }
    setArmedExitSymbol(null);
    setExitStatus((s) => ({ ...s, [symbol]: "Submitting caged paper sell..." }));
    const routeSymbol = symbol.replace("/", "");
    const res = await apiPostOperator(`/api/positions/${encodeURIComponent(routeSymbol)}/manual-exit-request`, {
      actor: "portfolio_ui",
    });
    const status = res.ok
      ? `Result: ${String((res.data as Record<string, unknown> | null)?.status ?? "submitted")}`
      : `Blocked: ${res.error || `HTTP ${res.status}`}`;
    setExitStatus((s) => ({ ...s, [symbol]: status }));
    await load();
  }

  const brokerTruth = (recon?.broker_truth as Record<string, unknown>) || {};
  const brokerRows = (brokerTruth.positions as BrokerRow[]) || [];
  const warning = recon?.reconciliation_warning as string | undefined;
  const localTruth = (recon?.local_truth as Record<string, unknown>) || {};

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
          {(warning || nextAction) && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                {warning && <p>{warning}</p>}
                {nextAction && <p className="text-xs mt-1 opacity-90">{nextAction}</p>}
              </div>
            </div>
          )}

          <GlassPanel title="Broker truth (Alpaca paper)">
            <p className="text-[11px] text-slate-500 mb-2">
              Synced at {String(brokerTruth.synced_at ?? "—")}
            </p>
            {brokerRows.length === 0 ? (
              <EmptyState message="No open broker positions." />
            ) : (
              <div className="space-y-3">
                {brokerRows.map((pos) => (
                  <article key={String(pos.symbol)} className="rounded-lg border border-white/5 bg-white/2 p-3 text-sm">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="font-semibold text-white">{String(pos.symbol)}</span>
                      <div className="flex items-center gap-2">
                        {pos.local_history_incomplete && (
                          <span className="text-[10px] text-amber-400">Local history incomplete</span>
                        )}
                        <button
                          type="button"
                          onClick={() => requestPaperSell(String(pos.symbol))}
                          className={
                            armedExitSymbol === String(pos.symbol)
                              ? "rounded border border-amber-300/60 bg-amber-400/15 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-100 hover:bg-amber-400/25"
                              : "rounded border border-rose-400/40 bg-rose-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-rose-200 hover:bg-rose-500/20"
                          }
                        >
                          {armedExitSymbol === String(pos.symbol) ? "Confirm paper sell" : "Paper sell"}
                        </button>
                      </div>
                    </div>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                      <dt className="text-slate-500">Qty</dt>
                      <dd className="text-white text-right">{String(pos.qty)}</dd>
                      <dt className="text-slate-500">Avg entry</dt>
                      <dd className="text-white text-right">{String(pos.avg_entry ?? "—")}</dd>
                      <dt className="text-slate-500">Current price</dt>
                      <dd className="text-white text-right">{String(pos.current_price ?? "—")}</dd>
                      <dt className="text-slate-500">Market value</dt>
                      <dd className="text-white text-right">{String(pos.market_value ?? "—")}</dd>
                      <dt className="text-slate-500">Unrealized P/L</dt>
                      <dd className={`text-right ${(pos.unrealized_pl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {String(pos.unrealized_pl ?? "—")}
                        {pos.unrealized_pl_pct != null ? ` (${pos.unrealized_pl_pct}%)` : ""}
                      </dd>
                    </dl>
                    {exitStatus[String(pos.symbol)] && (
                      <p className="mt-2 text-[11px] text-amber-200">{exitStatus[String(pos.symbol)]}</p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Local truth">
            <ul className="text-sm text-slate-400 space-y-1">
              <li>Reset epoch: {String((localTruth.reset_epoch as Record<string, unknown>)?.reset_epoch_id ?? "—")}</li>
              <li>Local orders: {String(localTruth.order_count ?? 0)}</li>
              <li>Execution logs: {String(localTruth.execution_log_count ?? 0)}</li>
            </ul>
            {positions.length > 0 && (
              <div className="mt-3 space-y-2">
                {positions.map((pos) => (
                  <div key={String(pos.symbol)} className="text-[11px] text-slate-500 border-t border-white/5 pt-2">
                    Local view: {String(pos.symbol)} qty {String(pos.qty ?? "—")} ({String(pos.source ?? "local")})
                  </div>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Open positions (legacy table)">
            {meta.positions?.error ? (
              <PanelError title="Positions fetch failed" meta={meta.positions} expectedShape='{ positions: [...] }' />
            ) : positions.length === 0 ? (
              <EmptyState message="No open positions." />
            ) : (
              <div className="space-y-3">
                {positions.map((pos) => (
                  <article key={String(pos.symbol)} className="rounded-lg border border-white/5 bg-white/2 p-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold text-white">{String(pos.symbol)}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-emerald-400 text-xs">{String(pos.source ?? "broker")}</span>
                        <button
                          type="button"
                          onClick={() => requestPaperSell(String(pos.symbol))}
                          className={
                            armedExitSymbol === String(pos.symbol)
                              ? "rounded border border-amber-300/60 bg-amber-400/15 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-100 hover:bg-amber-400/25"
                              : "rounded border border-rose-400/40 bg-rose-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-rose-200 hover:bg-rose-500/20"
                          }
                        >
                          {armedExitSymbol === String(pos.symbol) ? "Confirm paper sell" : "Paper sell"}
                        </button>
                      </div>
                    </div>
                    {exitStatus[String(pos.symbol)] && (
                      <p className="mt-2 text-[11px] text-amber-200">{exitStatus[String(pos.symbol)]}</p>
                    )}
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
