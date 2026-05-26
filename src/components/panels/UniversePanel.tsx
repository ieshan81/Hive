"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Globe } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";

type SymbolRow = {
  symbol: string;
  asset_type: string;
  status: string;
  tradable_now: boolean;
  source?: string;
  blocked_reason?: string;
  quote_currency?: string;
  funding_status?: string;
  bar_freshness?: string;
  quote_freshness?: string;
  last_scan_at?: string;
};

type SourcesSummary = {
  source_counts?: Record<string, number>;
  why_only_8_crypto_displayed?: string;
  alpaca_crypto_api_called?: boolean;
  last_refresh_at?: string;
};

export function UniversePanel() {
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [sources, setSources] = useState<SourcesSummary | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "crypto" | "stock" | "blocked" | "watch">("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [st, src] = await Promise.all([
      apiGet<{ symbols?: SymbolRow[]; counts?: Record<string, number> }>("/api/universe/status"),
      apiGet<SourcesSummary>("/api/universe/sources"),
    ]);
    if (st.ok) {
      setSymbols(st.data?.symbols ?? []);
      setCounts(st.data?.counts ?? {});
    }
    if (src.ok) setSources(src.data ?? null);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const filtered = useMemo(() => {
    return symbols.filter((r) => {
      if (filter === "all") return true;
      if (filter === "active") return r.status === "Active";
      if (filter === "crypto") return r.asset_type === "Crypto";
      if (filter === "stock") return r.asset_type === "Stock";
      if (filter === "blocked") return r.status === "Blocked";
      if (filter === "watch") return r.status === "Watch-only";
      return true;
    });
  }, [symbols, filter]);

  if (loading) return <EmptyState message="Loading universe…" />;

  const sc = sources?.source_counts ?? {};

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Globe className="h-6 w-6 text-hive-cyan" />
        Universe
      </h1>
      <p className="text-sm text-slate-400">
        Alpaca-supported universe + curated watchlist · {counts.total ?? symbols.length} displayed ·{" "}
        {counts.active ?? 0} active · {counts.blocked ?? 0} blocked · {counts.crypto ?? 0} crypto ·{" "}
        {counts.stock ?? 0} stocks
      </p>

      <GlassPanel title="Source proof">
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px]">
          <div>
            <dt className="text-slate-500">Alpaca crypto API</dt>
            <dd className="text-white">{sc.alpaca_crypto_assets_api ?? "—"} assets</dd>
          </div>
          <div>
            <dt className="text-slate-500">Curated crypto</dt>
            <dd className="text-white">{sc.curated_crypto_watchlist ?? 8} shown</dd>
          </div>
          <div>
            <dt className="text-slate-500">Curated stocks</dt>
            <dd className="text-white">{sc.curated_stock_watchlist ?? 10}</dd>
          </div>
          <div>
            <dt className="text-slate-500">API called</dt>
            <dd className="text-white">{sources?.alpaca_crypto_api_called ? "yes" : "no"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Last refresh</dt>
            <dd className="text-white">{sources?.last_refresh_at?.slice(0, 19) ?? "—"}</dd>
          </div>
        </dl>
        {sources?.why_only_8_crypto_displayed && (
          <p className="text-[10px] text-slate-500 mt-2">{sources.why_only_8_crypto_displayed}</p>
        )}
      </GlassPanel>

      <div className="flex flex-wrap gap-1">
        {(["all", "active", "crypto", "stock", "blocked", "watch"] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={`text-[10px] px-2 py-1 rounded capitalize ${
              filter === key ? "bg-hive-cyan/20 text-hive-cyan" : "bg-slate-800 text-slate-400"
            }`}
          >
            {key}
          </button>
        ))}
      </div>

      <GlassPanel title={`Symbols (${filtered.length})`}>
        <div className="overflow-x-auto max-h-[70vh]">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pb-2 pr-2">Symbol</th>
                <th className="pb-2 pr-2">Type</th>
                <th className="pb-2 pr-2">Source</th>
                <th className="pb-2 pr-2">Status</th>
                <th className="pb-2 pr-2">Bars</th>
                <th className="pb-2 pr-2">Quote</th>
                <th className="pb-2">Block reason</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.symbol} className="border-t border-white/5 text-slate-300">
                  <td className="py-1.5 pr-2 font-medium text-white">{r.symbol}</td>
                  <td className="py-1.5 pr-2">{r.asset_type}</td>
                  <td className="py-1.5 pr-2 text-slate-500">{(r.source ?? "—").replace(/_/g, " ")}</td>
                  <td className="py-1.5 pr-2">{r.status}</td>
                  <td className="py-1.5 pr-2">{r.bar_freshness ?? "—"}</td>
                  <td className="py-1.5 pr-2">{r.quote_freshness ?? "—"}</td>
                  <td className="py-1.5 text-slate-500">{r.blocked_reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>
    </section>
  );
}
