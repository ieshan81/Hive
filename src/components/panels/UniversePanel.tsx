"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Globe } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { symbolIdentity } from "@/lib/symbolIdentity";

type SymbolRow = {
  symbol: string;
  asset_type?: string;
  status?: string;
  tradable_now?: boolean;
  source?: string;
  blocked_reason?: string;
  block_reason?: string;
  quote_currency?: string;
  funding_status?: string;
  bar_freshness?: string;
  quote_freshness?: string;
  last_scan_at?: string;
  universe_rank_score?: number;
};

type SourcesSummary = {
  source_counts?: Record<string, number>;
  source_note?: string;
  alpaca_crypto_api_called?: boolean;
  last_refresh_at?: string;
};

type UniverseStatusPayload = {
  sources_summary?: {
    source_counts?: Record<string, number>;
    alpaca_crypto_api_called?: boolean;
    last_refresh_at?: string;
  };
  groups?: {
    crypto_universe?: SymbolRow[];
    stock_universe?: SymbolRow[];
    active_push_pull_candidates?: SymbolRow[];
  };
};

const FILTERS = ["all", "ranked", "crypto", "stock", "blocked", "watch"] as const;

function humanize(key: string): string {
  const known: Record<string, string> = {
    stale_bar: "Stale candle data",
    stale_bar_1m: "Stale one-minute candles",
    stale_or_missing_quote: "Missing fresh quote",
    liquidity_too_low: "Liquidity too low",
    insufficient_historical_bars: "Not enough candle history",
    account_not_eligible: "Account cannot trade pair",
    spread_too_wide: "Spread too wide",
    edge_after_cost_not_positive: "No edge after cost",
  };
  return known[key] ?? key.replace(/_/g, " ");
}

export function UniversePanel() {
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [blockBreakdown, setBlockBreakdown] = useState<Record<string, number>>({});
  const [sources, setSources] = useState<SourcesSummary | null>(null);
  const [mode, setMode] = useState<{
    mode_label?: string;
    mode_explanation?: string;
    stocks_session_note?: string;
    active_mode?: string;
  } | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const statusRes = await apiGet<UniverseStatusPayload>("/api/universe/status", { timeoutMs: 10000 });
    const statusData = statusRes.ok ? statusRes.data : null;
    const statusSymbols = [
      ...(statusData?.groups?.crypto_universe ?? []),
      ...(statusData?.groups?.stock_universe ?? []),
    ].filter((s) => s.symbol);
    const statusBySymbol = new Map(statusSymbols.map((s) => [s.symbol, s]));
    const statusSourceCounts = statusData?.sources_summary?.source_counts ?? {};
    const activeCrypto = statusData?.groups?.active_push_pull_candidates ?? statusData?.groups?.crypto_universe ?? [];
    const activeFresh = activeCrypto.filter((s) => s.bar_freshness === "fresh").length;
    if (statusData) {
      const usdPairs = Number(statusSourceCounts.alpaca_crypto_usd_pairs ?? statusSymbols.length);
      setSymbols(statusSymbols);
      setBlockBreakdown({});
      setCounts({
        total: usdPairs,
        cached: usdPairs,
        fresh: activeFresh,
        eligible: activeCrypto.length,
        ranked: 0,
        shortlist: 0,
        displayed: statusSymbols.length,
      });
      setSources({
        source_counts: {
          alpaca_crypto_assets_api: Number(statusSourceCounts.alpaca_crypto_assets_api ?? statusSymbols.length),
          alpaca_crypto_usd_pairs: usdPairs,
          displayed_pairs: Number(statusSourceCounts.display_universe_total ?? statusSymbols.length),
        },
        alpaca_crypto_api_called: Boolean(statusData.sources_summary?.alpaca_crypto_api_called),
        last_refresh_at: statusData.sources_summary?.last_refresh_at,
        source_note: `${usdPairs} USD crypto pairs available. Showing ${statusSymbols.length} fast-status rows; ${activeFresh} active crypto symbols have fresh cached candles.`,
      });
      setMode({
        mode_label: "Hybrid Radar",
        active_mode: "hybrid_radar",
        mode_explanation: "Fast status truth is shown first so a slow full snapshot cannot masquerade as zero universe.",
      });
      setLoading(false);
      return;
    }
    const ps = await apiGet<Record<string, unknown>>("/api/page-state/universe", { timeoutMs: 10000 });
    if (ps.ok && ps.data) {
      const d = ps.data;
      const rawSyms = ((d.symbols as SymbolRow[]) ?? []).filter((s) => s.symbol);
      const syms = (rawSyms.length > 0 ? rawSyms : statusSymbols).map((s) => {
        const live = statusBySymbol.get(s.symbol);
        if (!live) return s;
        return {
          ...s,
          asset_type: s.asset_type ?? live.asset_type,
          status: live.status ?? s.status,
          tradable_now: live.tradable_now ?? s.tradable_now,
          source: s.source ?? live.source,
          blocked_reason: live.blocked_reason ?? s.blocked_reason,
          quote_currency: s.quote_currency ?? live.quote_currency,
          funding_status: s.funding_status ?? live.funding_status,
          bar_freshness: live.bar_freshness ?? s.bar_freshness,
          quote_freshness: live.quote_freshness ?? s.quote_freshness,
          last_scan_at: live.last_scan_at ?? s.last_scan_at,
        };
      });
      const f = (d.funnel as Record<string, number>) ?? {};
      const blockers = (d.block_breakdown as Record<string, number>) ?? {};
      const c = (d.counts as Record<string, number>) ?? {};
      const sp = (d.source_proof as Record<string, unknown>) ?? {};
      const availableUsdPairs = Math.max(
        Number(f.available ?? 0),
        Number(c.available_usd_pairs ?? 0),
        Number(statusSourceCounts.alpaca_crypto_usd_pairs ?? 0)
      );
      const cachedUsdPairs = Math.max(
        Number(f.cached ?? 0),
        Number(c.cached_usd_pairs ?? 0),
        Number(statusSourceCounts.alpaca_crypto_usd_pairs ?? 0)
      );
      const staleFullFanout = Number(f.fresh ?? c.fresh ?? c.fresh_count ?? 0) === 0 && activeFresh > 0;

      setSymbols(syms);
      setBlockBreakdown(blockers);
      setCounts({
        total: availableUsdPairs || syms.length,
        cached: cachedUsdPairs || syms.length,
        fresh: Math.max(Number(f.fresh ?? c.fresh ?? c.fresh_count ?? 0), activeFresh),
        eligible: Math.max(Number(f.eligible ?? c.eligible ?? 0), activeFresh > 0 ? activeCrypto.length : 0),
        ranked: f.ranked ?? c.ranked ?? 0,
        shortlist: f.execution_shortlist ?? c.execution_shortlist ?? 0,
        displayed: syms.length,
      });
      setSources({
        source_counts: {
          alpaca_crypto_assets_api: Number(
            statusSourceCounts.alpaca_crypto_assets_api ?? sp.usd_pair_count ?? syms.length
          ),
          alpaca_crypto_usd_pairs: Number(statusSourceCounts.alpaca_crypto_usd_pairs ?? sp.usd_pair_count ?? syms.length),
          displayed_pairs: Number(statusSourceCounts.display_universe_total ?? sp.curated_crypto_displayed ?? syms.length),
        },
        alpaca_crypto_api_called: Boolean(sp.api_called),
        last_refresh_at: sp.last_successful_scan as string | undefined,
        source_note:
          staleFullFanout
            ? `Full 36-pair shortlist cache says stale; fast status confirms ${activeFresh} active crypto symbols have fresh cached candles.`
            : syms.length > 8
            ? `Hybrid radar is showing ${syms.length} cached USD pairs, not a tiny curated list.`
            : "This is a reduced cached display. Run a radar refresh to rebuild the broader universe.",
      });
      setMode({
        mode_label: String(d.mode_label ?? "Hybrid Radar"),
        active_mode: String(d.active_mode ?? "hybrid_radar"),
        mode_explanation: d.cached_data_used
          ? "Using cached radar truth. The paper tick refreshes candles before symbols can become entry-eligible."
          : undefined,
      });
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    return symbols.filter((r) => {
      const status = String(r.status ?? "");
      const assetType = String(r.asset_type ?? "");
      if (filter === "all") return true;
      if (filter === "ranked") return status === "Ranked" || Number(r.universe_rank_score ?? 0) > 0;
      if (filter === "crypto") return assetType === "Crypto";
      if (filter === "stock") return assetType === "Stock";
      if (filter === "blocked") return status === "Blocked" || Boolean(r.blocked_reason ?? r.block_reason);
      if (filter === "watch") return status === "Watch-only" || status === "Cached";
      return true;
    });
  }, [symbols, filter]);

  if (loading) return <EmptyState message="Loading universe..." />;

  const sc = sources?.source_counts ?? {};
  const topBlockers = Object.entries(blockBreakdown)
    .filter(([, value]) => Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6);

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Globe className="h-6 w-6 text-hive-cyan" />
        Universe
      </h1>
      <p className="text-sm text-slate-400">
        Mode: <span className="text-hive-cyan">{mode?.mode_label ?? "Hybrid Radar"}</span> |{" "}
        {counts.total ?? symbols.length} available | {counts.cached ?? 0} cached | {counts.eligible ?? 0} eligible
      </p>
      {mode?.mode_explanation && <p className="text-[11px] text-slate-500">{mode.mode_explanation}</p>}
      {mode?.stocks_session_note && <p className="text-[11px] text-amber-300/80">{mode.stocks_session_note}</p>}

      <GlassPanel title="Radar funnel">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
          {[
            ["Available", counts.total],
            ["Cached", counts.cached],
            ["Fresh Data", counts.fresh],
            ["Eligible", counts.eligible],
            ["Ranked", counts.ranked],
            ["Shortlist", counts.shortlist],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-md border border-white/10 bg-white/[0.03] p-3">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
              <p className="text-lg font-semibold text-white">{String(value ?? 0)}</p>
            </div>
          ))}
        </div>
        {topBlockers.length > 0 ? (
          <div className="mt-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Top blockers</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {topBlockers.map(([key, value]) => (
                <span
                  key={key}
                  className="rounded border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-[11px] text-amber-200"
                >
                  {humanize(key)}: {Number(value)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </GlassPanel>

      <GlassPanel title="Source proof">
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px]">
          <div>
            <dt className="text-slate-500">Alpaca crypto API</dt>
            <dd className="text-white">{sc.alpaca_crypto_assets_api ?? "-"} assets</dd>
          </div>
          <div>
            <dt className="text-slate-500">USD pairs</dt>
            <dd className="text-white">{sc.alpaca_crypto_usd_pairs ?? "-"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Displayed pairs</dt>
            <dd className="text-white">{sc.displayed_pairs ?? symbols.length}</dd>
          </div>
          <div>
            <dt className="text-slate-500">API called</dt>
            <dd className="text-white">{sources?.alpaca_crypto_api_called ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Last refresh</dt>
            <dd className="text-white">{sources?.last_refresh_at?.slice(0, 19) ?? "-"}</dd>
          </div>
        </dl>
        {sources?.source_note && <p className="text-[10px] text-slate-500 mt-2">{sources.source_note}</p>}
      </GlassPanel>

      <div className="flex flex-wrap gap-1">
        {FILTERS.map((key) => (
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
              {filtered.map((r) => {
                const id = symbolIdentity(r.symbol);
                const block = r.blocked_reason || r.block_reason || "";
                return (
                  <tr key={r.symbol} className="border-t border-white/5 text-slate-300">
                    <td className="py-1.5 pr-2 font-medium text-white flex items-center gap-2">
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded bg-hive-cyan/10 text-[10px] text-hive-cyan">
                        {id.glyph || id.name.slice(0, 2)}
                      </span>
                      {r.symbol}
                    </td>
                    <td className="py-1.5 pr-2">{r.asset_type ?? "Crypto"}</td>
                    <td className="py-1.5 pr-2 text-slate-500">{humanize(r.source ?? "-")}</td>
                    <td className="py-1.5 pr-2">{r.status ?? "Cached"}</td>
                    <td className="py-1.5 pr-2">{humanize(r.bar_freshness ?? "-")}</td>
                    <td className="py-1.5 pr-2">{humanize(r.quote_freshness ?? "-")}</td>
                    <td className="py-1.5 text-slate-500">{block ? humanize(block) : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassPanel>
    </section>
  );
}
