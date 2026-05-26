"use client";

import { useCallback, useEffect, useState } from "react";
import { Globe } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";

type SymbolRow = {
  symbol: string;
  asset_type: string;
  status: string;
  tradable_now: boolean;
  blocked_reason?: string;
  quote_currency?: string;
  last_scan_at?: string;
};

export function UniversePanel() {
  const [groups, setGroups] = useState<Record<string, SymbolRow[]>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiGet<{ groups?: Record<string, SymbolRow[]> }>("/api/universe/status");
    if (res.ok && res.data?.groups) setGroups(res.data.groups);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  if (loading) return <EmptyState message="Loading universe…" />;

  const sections: { key: string; title: string }[] = [
    { key: "active_push_pull_candidates", title: "Active push-pull candidates" },
    { key: "crypto_universe", title: "Crypto universe" },
    { key: "stock_universe", title: "Stock universe" },
    { key: "blocked_unsupported", title: "Blocked / unsupported" },
    { key: "recently_rejected", title: "Recently rejected" },
  ];

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Globe className="h-6 w-6 text-hive-cyan" />
        Universe
      </h1>
      <p className="text-sm text-slate-400">Symbols the bot scans — active, blocked, and tradable now.</p>

      {sections.map(({ key, title }) => {
        const rows = groups[key] ?? [];
        if (rows.length === 0) return null;
        return (
          <GlassPanel key={key} title={title}>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-slate-500 text-left">
                    <th className="pb-2 pr-3">Symbol</th>
                    <th className="pb-2 pr-3">Type</th>
                    <th className="pb-2 pr-3">Status</th>
                    <th className="pb-2 pr-3">Tradable</th>
                    <th className="pb-2">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${key}-${r.symbol}`} className="border-t border-white/5 text-slate-300">
                      <td className="py-1.5 pr-3 font-medium text-white">{r.symbol}</td>
                      <td className="py-1.5 pr-3">{r.asset_type}</td>
                      <td className="py-1.5 pr-3">{r.status}</td>
                      <td className="py-1.5 pr-3">{r.tradable_now ? "yes" : "no"}</td>
                      <td className="py-1.5 text-slate-500">{r.blocked_reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassPanel>
        );
      })}
    </section>
  );
}
