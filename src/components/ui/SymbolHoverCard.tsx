"use client";

import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { cachedSymbolMetadata, fetchSymbolMetadata, type SymbolMetadata } from "@/lib/symbolMetadata";

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <span className="flex justify-between gap-3">
      <span className="text-slate-500">{k}</span>
      <span className="text-slate-300 truncate max-w-[120px]">{v ?? "—"}</span>
    </span>
  );
}

/** Wraps a symbol element; on hover fetches /api/symbols/metadata (cached per symbol). */
export function SymbolHoverCard({ symbol, children }: { symbol: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [meta, setMeta] = useState<SymbolMetadata | null>(() => cachedSymbolMetadata(symbol) ?? null);
  const [loading, setLoading] = useState(false);

  const onEnter = useCallback(() => {
    setOpen(true);
    if (meta) return;
    setLoading(true);
    fetchSymbolMetadata(symbol)
      .then((m) => setMeta(m))
      .finally(() => setLoading(false));
  }, [symbol, meta]);

  const pnl = meta?.latest_trade_pnl;
  return (
    <span className="relative inline-flex" onMouseEnter={onEnter} onMouseLeave={() => setOpen(false)}>
      {children}
      {open && (
        <span className="absolute left-0 top-full z-50 mt-1 block w-60 rounded-lg border border-white/10 bg-slate-900/95 p-2 text-[10px] shadow-xl backdrop-blur">
          {loading && !meta ? (
            <span className="text-slate-400">Loading…</span>
          ) : !meta ? (
            <span className="text-slate-500">Metadata unavailable.</span>
          ) : (
            <span className="block space-y-0.5">
              <span className="block text-[11px] font-semibold text-white">{meta.full_name || "Name unavailable"}</span>
              <span className="mb-1 block text-slate-400">
                {meta.display_symbol || symbol} · {meta.asset_class || "unknown"}
              </span>
              <Row k="Venue" v={meta.venue} />
              <Row k="Tradable" v={meta.tradable == null ? null : meta.tradable ? "yes" : "no"} />
              <Row k="Session" v={meta.session_type} />
              <Row k="Last price" v={meta.last_price != null ? `$${meta.last_price}` : null} />
              <Row k="Spread" v={meta.spread_pct != null ? `${meta.spread_pct}%` : null} />
              <Row k="Sentiment" v={meta.latest_sentiment != null ? String(meta.latest_sentiment) : null} />
              <Row
                k="Latest P&L"
                v={
                  pnl != null ? (
                    <span className={pnl >= 0 ? "text-emerald-400" : "text-red-400"}>{`$${pnl.toFixed(2)}`}</span>
                  ) : null
                }
              />
              <Row k="Strategy" v={meta.latest_strategy} />
            </span>
          )}
        </span>
      )}
    </span>
  );
}
