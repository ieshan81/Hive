"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Globe } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { apiGet } from "@/lib/apiClient";

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
  trade_quality_score?: number;
  stop_loss?: number;
  take_profit?: number;
  pattern_name?: string;
  entry_allowed?: boolean;
};

type EligibleRow = SymbolRow & {
  push_score?: number;
  no_trade_reason?: string;
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

const FILTERS = ["all", "eligible", "crypto", "stock", "blocked", "watch"] as const;

const FUNNEL_STAGES = [
  ["available", "Available"],
  ["cached", "Cached"],
  ["fresh", "Fresh"],
  ["eligible", "Eligible"],
  ["to_trade", "Shortlist"],
] as const;

function humanize(key: string): string {
  const known: Record<string, string> = {
    stale_bar: "Stale candle data",
    stale_bar_1m: "Stale one-minute candles",
    stale_or_missing_quote: "Missing fresh quote",
    stale_quote: "Stale quote",
    liquidity_too_low: "Liquidity too low",
    insufficient_historical_bars: "Not enough candle history",
    account_not_eligible: "Account cannot trade pair",
    spread_too_wide: "Spread too wide",
    edge_after_cost_not_positive: "No edge after cost",
    negative_edge_after_cost: "No edge after cost",
    bearish_structure_no_long_entry: "Bearish structure",
  };
  return known[key] ?? key.replace(/_/g, " ");
}

function symbolKey(symbol: string): string {
  return String(symbol || "").toUpperCase().replace(/[/-]/g, "");
}

function dedupeBySymbol<T extends { symbol: string; trade_quality_score?: number; universe_rank_score?: number }>(rows: T[]): T[] {
  const best = new Map<string, T>();
  for (const row of rows.filter((r) => r.symbol)) {
    const key = symbolKey(row.symbol);
    const prev = best.get(key);
    const prevScore = Number(prev?.trade_quality_score ?? prev?.universe_rank_score ?? 0);
    const nextScore = Number(row.trade_quality_score ?? row.universe_rank_score ?? 0);
    if (!prev || nextScore >= prevScore) best.set(key, row);
  }
  return Array.from(best.values());
}

export function UniversePanel() {
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [eligibleTrades, setEligibleTrades] = useState<EligibleRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const [blockBreakdown, setBlockBreakdown] = useState<Record<string, number>>({});
  const [sources, setSources] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  // True when the fast summary could not be confirmed -> render unknown/grey, never a false zero.
  const [unknownTruth, setUnknownTruth] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [loading, setLoading] = useState(true);

  const eligibleSet = useMemo(
    () => new Set(eligibleTrades.map((r) => r.symbol.toUpperCase())),
    [eligibleTrades]
  );

  const load = useCallback(async () => {
    setLoading(true);
    // FAST top cards from the summary fast path — never blocked by the slow /status build, and
    // unknown source -> null (rendered grey), never a false zero.
    const sumRes = await apiGet<Record<string, unknown>>("/api/universe/summary", { timeoutMs: 6000 });
    if (sumRes.ok && sumRes.data) {
      const s = sumRes.data as Record<string, unknown>;
      const f = (s.funnel_counts ?? {}) as Record<string, number | null>;
      const fr = (s.freshness_counts ?? {}) as Record<string, number | null>;
      const src = (s.source_counts ?? {}) as Record<string, number | null>;
      const disp = (s.display_counts ?? {}) as Record<string, number | null>;
      setCounts({
        available: f.available ?? null,
        cached: fr.cached ?? null,
        fresh: fr.fresh ?? null,
        eligible: f.eligible ?? null,
        to_trade: f.to_trade ?? null,
        displayed: disp.total ?? null,
      });
      setSources({
        source_counts: {
          alpaca_crypto_assets_api: src.alpaca_crypto_assets,
          alpaca_crypto_usd_pairs: src.alpaca_crypto_usd_pairs,
          displayed_pairs: disp.total,
        },
        curated_crypto: src.curated_crypto,
        curated_stock: src.curated_stock,
        last_refresh_at: s.last_successful_scan_at,
        fast_path: true,
        status_latency_risk: s.status_latency_risk,
      });
      setSummary(
        (s.zero_eligible_explanation as string) ??
          (s.source_nonzero_but_eligible_zero ? "Symbols scanned; none eligible yet — see blockers below." : null)
      );
      setBlockBreakdown(
        Object.fromEntries(((s.blocker_summary ?? []) as Array<Record<string, unknown>>).map((b) => [String(b.code), Number(b.count)]))
      );
      setUnknownTruth(false);
    } else {
      // Could not confirm fast truth — render unknown/grey, never a false zero.
      setUnknownTruth(true);
    }
    setLoading(false);

    // Detail table + eligible rows from the slow endpoints (longer budget; does NOT block top cards).
    void Promise.all([
      apiGet<UniverseStatusPayload>("/api/universe/status", { timeoutMs: 16000 }),
      apiGet<Record<string, unknown>>("/api/universe/eligible-trades", { timeoutMs: 8000 }),
    ]).then(([statusRes, eligibleRes]) => {
      const statusData = statusRes.ok ? statusRes.data : null;
      const eligibleData = eligibleRes.ok ? eligibleRes.data : null;
      const statusSymbols = dedupeBySymbol([
        ...(statusData?.groups?.crypto_universe ?? []),
        ...(statusData?.groups?.stock_universe ?? []),
      ].filter((s) => s.symbol));
      const eligibleRows = dedupeBySymbol(
        ((eligibleData?.eligible_trades ?? eligibleData?.shortlist ?? []) as EligibleRow[])
      );
      if (eligibleRows.length > 0 || statusSymbols.length > 0) {
        setEligibleTrades(eligibleRows);
        setSymbols(statusSymbols.length > 0 ? statusSymbols : eligibleRows);
      }
      const bb =
        (eligibleData?.no_trade_reason_breakdown as Record<string, number>) ??
        (eligibleData?.block_breakdown as Record<string, number>);
      if (bb && Object.keys(bb).length > 0) setBlockBreakdown(bb);
    });
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const filtered = useMemo(() => {
    return symbols.filter((r) => {
      const status = String(r.status ?? "");
      const assetType = String(r.asset_type ?? "");
      const isEligible = eligibleSet.has(r.symbol.toUpperCase()) || r.entry_allowed;
      if (filter === "all") return true;
      if (filter === "eligible") return isEligible;
      if (filter === "crypto") return assetType === "Crypto" || r.symbol.includes("/");
      if (filter === "stock") return assetType === "Stock";
      if (filter === "blocked") return status === "Blocked" || Boolean(r.blocked_reason ?? r.block_reason);
      if (filter === "watch") return status === "Watch-only" || status === "Cached";
      return true;
    });
  }, [symbols, filter, eligibleSet]);

  if (loading) return <EmptyState message="Loading universe scan…" />;

  const sc = (sources?.source_counts ?? {}) as Record<string, number>;
  const topBlockers = Object.entries(blockBreakdown)
    .filter(([, value]) => Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6);

  return (
    <section className="space-y-4 max-w-5xl">
      <header>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Globe className="h-6 w-6 text-hive-cyan" />
          Universe
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Hybrid Radar · full scan · no shortlist cap · trade every eligible symbol each cycle
        </p>
        {summary && <p className="text-[11px] text-hive-cyan/90 mt-2">{summary}</p>}
      </header>

      <GlassPanel title="Radar funnel">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          {FUNNEL_STAGES.map(([key, label]) => {
            const v = counts[key];
            const isUnknown = unknownTruth || v === null || v === undefined;
            return (
              <div key={key} className="rounded-md border border-white/10 bg-white/[0.03] p-3">
                <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
                <p className={`text-lg font-semibold ${isUnknown ? "text-slate-500" : "text-white"}`}>
                  {isUnknown ? "—" : String(v)}
                </p>
              </div>
            );
          })}
        </div>
        {topBlockers.length > 0 && (
          <div className="mt-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Why symbols drop out</p>
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
        )}
      </GlassPanel>

      <GlassPanel title={`Paper candidates (${eligibleTrades.length})`}>
        <p className="text-[10px] text-slate-500 mb-2">
          Shortlist ({counts.to_trade ?? "—"}) = execution shortlist · Paper candidates = alpha-approved broker entries
        </p>
        {eligibleTrades.length === 0 ? (
          <p className="text-[11px] text-slate-500">
            Paper candidates: 0 · Reason: Alpha not ready / no scorecard — shortlist symbols still need evidence.
          </p>
        ) : (
          <ul className="space-y-1.5 max-h-[320px] overflow-y-auto">
            {eligibleTrades.map((s) => (
              <li
                key={s.symbol}
                className="flex items-center justify-between gap-3 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-3 py-2"
              >
                <div className="flex-1 min-w-0">
                  <TickerSymbol symbol={s.symbol} assetClass={s.asset_type} size="sm" labelClassName="text-[12px] font-semibold text-white" />
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {s.pattern_name ? humanize(String(s.pattern_name)) : "Pattern setup"}
                    {s.stop_loss != null ? ` · SL ${Number(s.stop_loss).toFixed(4)}` : ""}
                    {s.take_profit != null ? ` · TP ${Number(s.take_profit).toFixed(4)}` : ""}
                  </p>
                </div>
                <span className="text-hive-cyan mono-metric text-sm font-bold shrink-0">
                  Q{(((s.trade_quality_score ?? s.universe_rank_score ?? 0) as number) * 100).toFixed(0)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <GlassPanel title="Source proof">
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px]">
          <div>
            <dt className="text-slate-500">Alpaca crypto API</dt>
            <dd className="text-white">{sc.alpaca_crypto_assets_api ?? "—"} assets</dd>
          </div>
          <div>
            <dt className="text-slate-500">USD pairs</dt>
            <dd className="text-white">{sc.alpaca_crypto_usd_pairs ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Displayed</dt>
            <dd className="text-white">{sc.displayed_pairs ?? symbols.length}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Last refresh</dt>
            <dd className="text-white">{String(sources?.last_refresh_at ?? "—").slice(0, 19)}</dd>
          </div>
        </dl>
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

      <GlassPanel title={`All scanned symbols (${filtered.length})`}>
        <div className="overflow-x-auto max-h-[60vh]">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pb-2 pr-2">Symbol</th>
                <th className="pb-2 pr-2">Type</th>
                <th className="pb-2 pr-2">Status</th>
                <th className="pb-2 pr-2">Bars</th>
                <th className="pb-2 pr-2">Quote</th>
                <th className="pb-2">Block reason</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const block = r.blocked_reason || r.block_reason || "";
                const isEligible = eligibleSet.has(r.symbol.toUpperCase());
                return (
                  <tr key={r.symbol} className="border-t border-white/5 text-slate-300">
                    <td className="py-1.5 pr-2 font-medium text-white">
                      <TickerSymbol symbol={r.symbol} assetClass={r.asset_type} size="sm" labelClassName="text-[11px] text-white" />
                    </td>
                    <td className="py-1.5 pr-2">{r.asset_type ?? (r.symbol.includes("/") ? "Crypto" : "Stock")}</td>
                    <td className="py-1.5 pr-2">
                      {isEligible ? (
                        <span className="text-emerald-400">Eligible</span>
                      ) : (
                        r.status ?? "Cached"
                      )}
                    </td>
                    <td className="py-1.5 pr-2">{humanize(r.bar_freshness ?? "—")}</td>
                    <td className="py-1.5 pr-2">{humanize(r.quote_freshness ?? "—")}</td>
                    <td className="py-1.5 text-slate-500">{block ? humanize(block) : "—"}</td>
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
