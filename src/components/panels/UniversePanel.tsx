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
  bar_freshness?: string;
  spread?: string;
  spread_pct?: number;
  price?: number;
};

type FilterKey = "all" | "active" | "crypto" | "stock" | "blocked" | "watch" | "rejected";

export function UniversePanel() {
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<FilterKey>("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiGet<{ symbols?: SymbolRow[]; counts?: Record<string, number> }>("/api/universe/status");
    if (res.ok) {
      setSymbols(res.data?.symbols ?? []);
      setCounts(res.data?.counts ?? {});
    }
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

  const filters: { key: FilterKey; label: string }[] = [
    { key: "all", label: "All" },
    { key: "active", label: "Active" },
    { key: "crypto", label: "Crypto" },
    { key: "stock", label: "Stocks" },
    { key: "blocked", label: "Blocked" },
    { key: "watch", label: "Watch-only" },
  ];

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Globe className="h-6 w-6 text-hive-cyan" />
        Universe
      </h1>
      <p className="text-sm text-slate-400">
        {counts.total ?? symbols.length} symbols · {counts.active ?? 0} active · {counts.blocked ?? 0} blocked ·{" "}
        {counts.crypto ?? 0} crypto · {counts.stock ?? 0} stocks
      </p>

      <div className="flex flex-wrap gap-1">
        {filters.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={`text-[10px] px-2 py-1 rounded ${
              filter === f.key ? "bg-hive-cyan/20 text-hive-cyan" : "bg-slate-800 text-slate-400"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <GlassPanel title={`Symbols (${filtered.length})`}>
        {filtered.length === 0 ? (
          <p className="text-sm text-slate-500">No symbols in this filter. Refresh or start paper learning.</p>
        ) : (
          <div className="overflow-x-auto max-h-[70vh]">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-slate-500 text-left">
                  <th className="pb-2 pr-2">Symbol</th>
                  <th className="pb-2 pr-2">Type</th>
                  <th className="pb-2 pr-2">Status</th>
                  <th className="pb-2 pr-2">Tradable</th>
                  <th className="pb-2 pr-2">Bars</th>
                  <th className="pb-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.symbol} className="border-t border-white/5 text-slate-300">
                    <td className="py-1.5 pr-2 font-medium text-white">{r.symbol}</td>
                    <td className="py-1.5 pr-2">{r.asset_type}</td>
                    <td className="py-1.5 pr-2">{r.status}</td>
                    <td className="py-1.5 pr-2">{r.tradable_now ? "yes" : "no"}</td>
                    <td className="py-1.5 pr-2">{r.bar_freshness ?? "—"}</td>
                    <td className="py-1.5 text-slate-500">{r.blocked_reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>
    </section>
  );
}
