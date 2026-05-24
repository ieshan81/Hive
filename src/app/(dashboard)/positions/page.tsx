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
  normalizePositionStates,
  normalizeTrades,
} from "@/lib/apiNormalize";
import type { OrderRecord, PanelLoadMeta, Position, PositionState, TradeHistoryRecord } from "@/types/api";

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [states, setStates] = useState<PositionState[]>([]);
  const [trades, setTrades] = useState<TradeHistoryRecord[]>([]);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<Record<string, PanelLoadMeta>>({});

  const load = useCallback(async () => {
    setLoading(true);
    const m: Record<string, PanelLoadMeta> = {};
    const ts = new Date().toISOString();

    const [pRes, sRes, tRes, oRes] = await Promise.all([
      apiGet("/api/positions"),
      apiGet("/api/positions/state"),
      apiGet("/api/trades/history"),
      apiGet("/api/orders"),
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

    if (sRes.ok) {
      setStates(normalizePositionStates(sRes.data));
      m.states = { source: "live_api", lastUpdated: ts, endpoint: "/api/positions/state", httpStatus: sRes.status };
    } else {
      setStates([]);
      m.states = {
        source: "empty",
        lastUpdated: ts,
        endpoint: "/api/positions/state",
        httpStatus: sRes.status,
        error: sRes.error || `HTTP ${sRes.status}`,
      };
    }

    if (tRes.ok) {
      setTrades(normalizeTrades(tRes.data));
      m.trades = { source: "live_api", lastUpdated: ts, endpoint: "/api/trades/history", httpStatus: tRes.status };
    } else {
      setTrades([]);
      m.trades = {
        source: "empty",
        lastUpdated: ts,
        endpoint: "/api/trades/history",
        httpStatus: tRes.status,
        error: tRes.error || `HTTP ${tRes.status}`,
      };
    }

    if (oRes.ok) {
      setOrders(normalizeOrders(oRes.data));
      m.orders = { source: "live_api", lastUpdated: ts, endpoint: "/api/orders", httpStatus: oRes.status };
    } else {
      setOrders([]);
      m.orders = {
        source: "empty",
        lastUpdated: ts,
        endpoint: "/api/orders",
        httpStatus: oRes.status,
        error: oRes.error || `HTTP ${oRes.status}`,
      };
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
          <h1 className="text-xl font-semibold text-white">Positions</h1>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="flex items-center gap-1 text-xs text-hive-cyan border border-hive-cyan/30 rounded px-3 py-1.5"
        >
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </header>

      {loading ? (
        <EmptyState message="Loading broker positions…" />
      ) : (
        <>
          <GlassPanel title="Current positions (broker-confirmed)">
            {meta.positions?.error ? (
              <PanelError title="Positions fetch failed" meta={meta.positions} expectedShape='{ positions: [...] }' />
            ) : positions.length === 0 ? (
              <EmptyState message="No open positions (endpoint OK, count 0)" />
            ) : (
              <div className="space-y-3">
                {positions.map((pos) => (
                  <article
                    key={String(pos.symbol)}
                    className="rounded-lg border border-white/5 bg-white/2 p-3 text-sm"
                  >
                    <div className="flex justify-between">
                      <span className="font-semibold text-white">{String(pos.symbol)}</span>
                      <span className="text-emerald-400 text-xs">{String(pos.source ?? "broker")}</span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2 text-xs text-slate-400">
                      <div>Qty: {Number(pos.qty).toFixed(4)}</div>
                      <div>Entry: {pos.avg_entry_price ?? pos.avgEntryPrice}</div>
                      <div>Price: {pos.current_price}</div>
                      <div className={Number(pos.unrealized_pl) >= 0 ? "text-emerald-400" : "text-red-400"}>
                        P/L: {pos.unrealized_pl} ({pos.unrealized_pl_pct}%)
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Position state">
            {meta.states?.error ? (
              <PanelError title="Position state fetch failed" meta={meta.states} expectedShape='{ states: [...] }' />
            ) : states.length === 0 ? (
              <EmptyState message="No enriched state (endpoint OK, count 0)" />
            ) : (
              <div className="space-y-2 text-xs">
                {states.map((s) => (
                  <div key={String(s.symbol)} className="border-b border-white/5 pb-2 text-slate-300">
                    <strong className="text-white">{s.symbol}</strong>
                    {s.fee_pct != null && (
                      <span className="text-amber-400 ml-2">fee {Number(s.fee_pct).toFixed(2)}%</span>
                    )}
                    {s.fee_adjusted_qty != null && (
                      <span className="text-slate-500 ml-2">adj qty {s.fee_adjusted_qty}</span>
                    )}
                    {s.cycle_run_id && (
                      <p className="text-slate-600 font-mono truncate mt-0.5">{s.cycle_run_id}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Trade history">
            {meta.trades?.error ? (
              <PanelError title="Trades fetch failed" meta={meta.trades} expectedShape='{ trades: [...] }' />
            ) : trades.length === 0 ? (
              <EmptyState message="No trades (endpoint OK, count 0)" />
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500">
                    <th className="text-left py-1">Symbol</th>
                    <th className="text-left">Side</th>
                    <th className="text-left">Status</th>
                    <th className="text-left">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={String(t.trade_id ?? t.symbol)} className="text-slate-300 border-t border-white/5">
                      <td className="py-1">{t.symbol}</td>
                      <td>{t.side}</td>
                      <td>{t.outcome ?? t.status}</td>
                      <td>{t.realized_pl ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </GlassPanel>

          <GlassPanel title="Orders history">
            {meta.orders?.error ? (
              <PanelError title="Orders fetch failed" meta={meta.orders} expectedShape='{ orders: [...] }' />
            ) : orders.length === 0 ? (
              <EmptyState message="No orders (endpoint OK, count 0)" />
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500">
                    <th className="text-left py-1">Symbol</th>
                    <th className="text-left">Status</th>
                    <th className="text-left">Fill</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o, i) => (
                    <tr key={String(o.broker_order_id ?? o.client_order_id ?? i)} className="text-slate-300 border-t border-white/5">
                      <td className="py-1">{o.symbol}</td>
                      <td>{o.status}</td>
                      <td>{o.filled_avg_price ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </GlassPanel>
        </>
      )}
    </section>
  );
}
