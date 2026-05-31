"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { SymbolHoverCard } from "@/components/ui/SymbolHoverCard";
import { EmptyState } from "@/components/ui/EmptyState";

type LedgerOrder = {
  broker_order_id?: string | null;
  symbol?: string;
  display_symbol?: string;
  asset_class?: string;
  side?: string | null;
  order_type_label?: string | null;
  display_qty?: number | null;
  display_price?: number | null;
  status?: string | null;
  reject_reason?: string | null;
  reason?: string | null;
};
type LedgerTrade = { exit_order_id?: string | null; gross_pnl?: number | null };
type LedgerSummary = {
  closed_trades?: number;
  gross_pnl?: number | null;
  estimated_net_pnl?: number | null;
  win_rate_pct?: number | null;
  biggest_winner?: number | null;
  biggest_loser?: number | null;
  open_positions?: number;
  dust_residual_count?: number;
  unmatched_count?: number;
  fees_available?: boolean;
};

function AssetChip({ ac }: { ac?: string }) {
  const cls =
    ac === "crypto"
      ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-300"
      : ac === "stock"
      ? "border-violet-500/40 bg-violet-500/10 text-violet-300"
      : "border-white/10 bg-white/5 text-slate-400";
  const label = ac === "crypto" ? "Crypto" : ac === "stock" ? "Stock" : "Unknown";
  return <span className={`rounded-full border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${cls}`}>{label}</span>;
}

function SideChip({ side }: { side?: string | null }) {
  const s = String(side || "").toLowerCase();
  if (s !== "buy" && s !== "sell") return <span className="text-slate-500">—</span>;
  const cls = s === "buy" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return <span className={`rounded-full border px-1.5 py-0.5 text-[9px] uppercase ${cls}`}>{s}</span>;
}

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  filled: { label: "Filled", cls: "text-emerald-400" },
  paper_order_filled: { label: "Filled", cls: "text-emerald-400" },
  rejected: { label: "Rejected", cls: "text-red-400" },
  paper_order_rejected: { label: "Rejected", cls: "text-red-400" },
  broker_rejected: { label: "Rejected", cls: "text-red-400" },
  preflight_blocked: { label: "Blocked", cls: "text-amber-400" },
  submitted: { label: "Sent", cls: "text-slate-300" },
  pending: { label: "Open", cls: "text-slate-400" },
};

function statusView(status?: string | null): { label: string; cls: string } {
  const s = String(status || "").toLowerCase();
  if (STATUS_MAP[s]) return STATUS_MAP[s];
  if (s.includes("reject")) return { label: "Rejected", cls: "text-red-400" };
  if (s.includes("block")) return { label: "Blocked", cls: "text-amber-400" };
  if (s.includes("fill")) return { label: "Filled", cls: "text-emerald-400" };
  return { label: status ? String(status) : "Open", cls: "text-slate-400" };
}

function num(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function SummaryBar({ s }: { s: LedgerSummary | null }) {
  if (!s) return null;
  const cell = (label: string, value: string, cls = "text-slate-200") => (
    <div className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-1.5">
      <p className="text-[9px] uppercase text-slate-500">{label}</p>
      <p className={`text-sm font-semibold mono-metric ${cls}`}>{value}</p>
    </div>
  );
  const gross = s.gross_pnl;
  const net = s.fees_available ? s.estimated_net_pnl : null;
  return (
    <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {cell("Closed trades", s.closed_trades != null ? String(s.closed_trades) : "Unavailable")}
      {cell("Gross P&L", gross != null ? `$${gross.toFixed(2)}` : "Unavailable", (gross ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}
      {cell("Net P&L (est.)", net != null ? `$${net.toFixed(2)}` : "Unavailable", "text-slate-300")}
      {cell("Win rate", s.win_rate_pct != null ? `${s.win_rate_pct}%` : "Unavailable")}
      {cell("Biggest win", s.biggest_winner != null ? `$${s.biggest_winner.toFixed(2)}` : "Unavailable", "text-emerald-400")}
      {cell("Biggest loss", s.biggest_loser != null ? `$${s.biggest_loser.toFixed(2)}` : "Unavailable", "text-red-400")}
      {cell("Open positions", s.open_positions != null ? String(s.open_positions) : "Unavailable")}
      {cell("Dust residual", s.dust_residual_count != null ? String(s.dust_residual_count) : "Unavailable", "text-amber-400")}
      {cell("Unmatched", s.unmatched_count != null ? String(s.unmatched_count) : "Unavailable", "text-amber-400")}
    </div>
  );
}

export function PortfolioOrdersLedger() {
  const [orders, setOrders] = useState<LedgerOrder[]>([]);
  const [pnlByExit, setPnlByExit] = useState<Record<string, number | null>>({});
  const [summary, setSummary] = useState<LedgerSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [oRes, tRes] = await Promise.all([
      apiGet<{ orders: LedgerOrder[] }>("/api/orders/ledger?limit=100", { timeoutMs: 8000 }),
      apiGet<{ trades: LedgerTrade[]; summary: LedgerSummary }>("/api/trades/ledger?limit=100", { timeoutMs: 8000 }),
    ]);
    if (oRes.ok && oRes.data) setOrders(oRes.data.orders || []);
    if (tRes.ok && tRes.data) {
      const m: Record<string, number | null> = {};
      for (const t of tRes.data.trades || []) if (t.exit_order_id) m[t.exit_order_id] = t.gross_pnl ?? null;
      setPnlByExit(m);
      setSummary(tRes.data.summary || null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <EmptyState message="Loading order ledger…" />;
  if (!orders.length) return <EmptyState message="No orders on record yet." />;

  return (
    <>
      <SummaryBar s={summary} />
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/5 text-slate-500">
              <th className="py-1 pr-2 text-left">Symbol</th>
              <th className="py-1 pr-2 text-left">Asset</th>
              <th className="py-1 pr-2 text-left">Side</th>
              <th className="py-1 pr-2 text-left">Qty</th>
              <th className="py-1 pr-2 text-left">Buy</th>
              <th className="py-1 pr-2 text-left">Sell</th>
              <th className="py-1 pr-2 text-left">P&amp;L</th>
              <th className="py-1 pr-2 text-left">Status</th>
              <th className="py-1 text-left">Reason</th>
            </tr>
          </thead>
          <tbody>
            {orders.slice(0, 50).map((o, i) => {
              const side = String(o.side || "").toLowerCase();
              const sym = o.display_symbol || o.symbol || "—";
              const st = statusView(o.status);
              const buy = side === "buy" ? o.display_price : null;
              const sell = side === "sell" ? o.display_price : null;
              const pnl = o.broker_order_id ? pnlByExit[o.broker_order_id] : null;
              const reason = o.reject_reason || o.reason || "—";
              return (
                <tr key={String(o.broker_order_id ?? i)} className="border-t border-white/5">
                  <td className="py-1.5 pr-2">
                    <SymbolHoverCard symbol={sym}>
                      <TickerSymbol symbol={sym} size="sm" labelClassName="text-[11px] text-slate-200" />
                    </SymbolHoverCard>
                  </td>
                  <td className="py-1.5 pr-2"><AssetChip ac={o.asset_class} /></td>
                  <td className="py-1.5 pr-2"><SideChip side={o.side} /></td>
                  <td className="py-1.5 pr-2 text-slate-300">{num(o.display_qty)}</td>
                  <td className="py-1.5 pr-2 text-slate-400">{buy != null ? num(buy) : "—"}</td>
                  <td className="py-1.5 pr-2 text-slate-400">{sell != null ? num(sell) : "—"}</td>
                  <td className={`py-1.5 pr-2 mono-metric ${pnl == null ? "text-slate-500" : pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {pnl == null ? "—" : `$${pnl.toFixed(2)}`}
                  </td>
                  <td className="py-1.5 pr-2">
                    <span className={st.cls}>{st.label}</span>
                    {o.order_type_label ? (
                      <span className="ml-1 text-[9px] text-slate-600" title="Order type">
                        {o.order_type_label}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-1.5 max-w-[200px] truncate text-slate-500" title={reason}>
                    {reason}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
