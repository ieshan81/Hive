"use client";

import { useCallback, useEffect, useState } from "react";
import { Wallet, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function PositionsPage() {
  const [positions, setPositions] = useState<Record<string, unknown>[]>([]);
  const [states, setStates] = useState<Record<string, unknown>[]>([]);
  const [trades, setTrades] = useState<Record<string, unknown>[]>([]);
  const [orders, setOrders] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, s, t, o] = await Promise.all([
        fetch(`${API_BASE}/api/positions`).then((r) => r.json()),
        fetch(`${API_BASE}/api/positions/state`).then((r) => r.json()),
        fetch(`${API_BASE}/api/trades/history`).then((r) => r.json()),
        fetch(`${API_BASE}/api/orders`).then((r) => r.json()),
      ]);
      setPositions(p.positions || []);
      setStates(s.states || []);
      setTrades(t.trades || []);
      setOrders(o.orders || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    await fetch(`${API_BASE}/api/positions/refresh`, { method: "POST" });
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
          className="flex items-center gap-1 text-xs text-hive-cyan border border-hive-cyan/30 rounded px-3 py-1.5 hover:bg-hive-cyan/10"
        >
          <RefreshCw className="h-3 w-3" /> Refresh positions
        </button>
      </header>

      {loading ? (
        <EmptyState message="Loading broker positions…" />
      ) : (
        <>
          <GlassPanel title="Current positions (broker-confirmed)">
            {positions.length === 0 ? (
              <EmptyState message="No open positions" />
            ) : (
              <div className="space-y-3">
                {positions.map((pos) => (
                  <article
                    key={String(pos.symbol)}
                    className="rounded-lg border border-white/5 bg-white/2 p-3 text-sm"
                  >
                    <div className="flex justify-between">
                      <span className="font-semibold text-white">{String(pos.symbol)}</span>
                      <span className="text-emerald-400 text-xs">{String(pos.source)}</span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2 text-xs text-slate-400">
                      <div>Qty: {String(pos.qty)}</div>
                      <div>Entry: {String(pos.avg_entry_price)}</div>
                      <div>Mkt: {String(pos.market_value)}</div>
                      <div className={Number(pos.unrealized_pl) >= 0 ? "text-emerald-400" : "text-red-400"}>
                        P/L: {String(pos.unrealized_pl)} ({String(pos.unrealized_pl_pct)}%)
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Position state">
            {states.length === 0 ? (
              <EmptyState message="No enriched state" />
            ) : (
              <pre className="text-[10px] text-slate-400 overflow-auto max-h-48">
                {JSON.stringify(states, null, 2)}
              </pre>
            )}
          </GlassPanel>

          <GlassPanel title="Trade history">
            {trades.length === 0 ? (
              <EmptyState message="No trades recorded yet" />
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
                    <tr key={String(t.trade_id)} className="text-slate-300 border-t border-white/5">
                      <td className="py-1">{String(t.symbol)}</td>
                      <td>{String(t.side)}</td>
                      <td>{String(t.outcome)}</td>
                      <td>{String(t.realized_pl ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </GlassPanel>

          <GlassPanel title="Orders history">
            {orders.length === 0 ? (
              <EmptyState message="No orders" />
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
                    <tr key={i} className="text-slate-300 border-t border-white/5">
                      <td className="py-1">{String(o.symbol)}</td>
                      <td>{String(o.status)}</td>
                      <td>{String(o.filled_avg_price ?? "—")}</td>
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
