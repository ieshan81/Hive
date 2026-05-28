"use client";

import { useCallback, useEffect, useState } from "react";
import { Radar, ChevronRight } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { AssetIcon } from "@/components/ui/AssetIcon";
import { apiGet } from "@/lib/apiClient";

type Funnel = {
  available: number;
  cached: number;
  fresh?: number;
  eligible: number;
  ranked: number;
  execution_shortlist: number;
};

type Shortlist = {
  symbol: string;
  universe_rank_score: number;
  rank_components?: {
    liquidity_pct: number;
    spread_pct_inv: number;
    volume_spike_pct: number;
    atr_pct: number;
    freshness_pct: number;
    cost_efficiency: number;
  };
  price?: number;
  spread_bps?: number;
  freshness?: number;
};

type Payload = {
  status: string;
  answer?: string;
  block_breakdown?: Record<string, number>;
  counts?: {
    available_usd_pairs?: number;
    cached_usd_pairs?: number;
    fresh?: number;
    fresh_count?: number;
    eligible?: number;
    ranked?: number;
    execution_shortlist?: number;
  };
  pipeline?: {
    cycle_id: string;
    funnel: Funnel;
    shortlist: Shortlist[];
    eligible?: Shortlist[];
  };
};

type UniverseStatusPayload = {
  sources_summary?: {
    status?: string;
    source_counts?: Record<string, number>;
  };
  groups?: {
    crypto_universe?: Array<{ bar_freshness?: string; status?: string }>;
    active_push_pull_candidates?: Array<{ bar_freshness?: string; status?: string }>;
  };
};

const STAGE_DEFS = [
  { key: "available" as const, label: "Available", color: "#849495" },
  { key: "cached" as const, label: "Cached", color: "#b9cacb" },
  { key: "fresh" as const, label: "Fresh Data", color: "#c8f3f5" },
  { key: "eligible" as const, label: "Eligible", color: "#00dbe9" },
  { key: "ranked" as const, label: "Ranked", color: "#00f0ff" },
  { key: "execution_shortlist" as const, label: "Shortlist", color: "#00FF66" },
];

function humanizeBlocker(key: string): string {
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

export function UniverseRadarFunnel() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const statusRes = await apiGet<UniverseStatusPayload>("/api/universe/status", { timeoutMs: 10000 });
    const statusData = statusRes.ok ? statusRes.data : null;
    const sourceCounts = statusData?.sources_summary?.source_counts ?? {};
    const activeCrypto = statusData?.groups?.active_push_pull_candidates ?? statusData?.groups?.crypto_universe ?? [];
    const activeFresh = activeCrypto.filter((s) => s.bar_freshness === "fresh").length;

    if (statusData) {
      const usdPairs = Number(sourceCounts.alpaca_crypto_usd_pairs ?? sourceCounts.display_universe_total ?? 0);
      setData({
        status: String(statusData.sources_summary?.status ?? "ok"),
        answer: `${usdPairs} USD crypto pairs available; ${activeFresh} active symbols have fresh cached candles. Shortlist remains 0 until push-pull, quote refresh, and preflight approve.`,
        block_breakdown: {},
        counts: {
          available_usd_pairs: usdPairs,
          cached_usd_pairs: usdPairs,
          fresh: activeFresh,
          eligible: activeCrypto.length,
          ranked: 0,
          execution_shortlist: 0,
        },
        pipeline: {
          cycle_id: "status",
          funnel: {
            available: usdPairs,
            cached: usdPairs,
            fresh: activeFresh,
            eligible: activeCrypto.length,
            ranked: 0,
            execution_shortlist: 0,
          },
          shortlist: [],
        },
      });
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const funnel = data?.pipeline?.funnel ?? (data?.counts
    ? {
        available: data.counts.available_usd_pairs ?? data.counts.cached_usd_pairs ?? 0,
        cached: data.counts.cached_usd_pairs ?? data.counts.available_usd_pairs ?? 0,
        fresh: data.counts.fresh ?? data.counts.fresh_count ?? 0,
        eligible: data.counts.eligible ?? 0,
        ranked: data.counts.ranked ?? 0,
        execution_shortlist: data.counts.execution_shortlist ?? 0,
      }
    : undefined);
  const shortlist =
    (data?.pipeline?.shortlist as Shortlist[]) ??
    ((data as { execution_shortlist?: Shortlist[] })?.execution_shortlist ?? []);
  const blockers = Object.entries(data?.block_breakdown ?? {})
    .filter(([, value]) => Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 4);

  return (
    <GlassPanel
      title="Universe Radar"
      icon={<Radar className="h-4 w-4" style={{ color: "#00dbe9" }} />}
    >
      <p className="text-[11px] text-[#b9cacb] mb-2">
        Radar scanned available assets → cached → fresh → eligible → ranked → execution shortlist
      </p>
      {data?.answer && (
        <p className="text-[10px] text-slate-500 mb-3">{String(data.answer).slice(0, 280)}</p>
      )}

      {/* Funnel chips */}
      <div className="flex items-center gap-1.5 flex-wrap mb-5">
        {STAGE_DEFS.map((stage, idx) => {
          const value = funnel?.[stage.key] ?? (loading ? "…" : 0);
          return (
            <div key={stage.key} className="flex items-center gap-1.5">
              <div
                className="px-2.5 py-1 rounded-md border flex items-center gap-1.5"
                style={{
                  borderColor: `${stage.color}55`,
                  background: `${stage.color}0d`,
                }}
              >
                <span className="label-caps" style={{ color: stage.color }}>
                  {stage.label}
                </span>
                <span
                  className="mono-metric text-[11px] font-bold"
                  style={{ color: stage.color }}
                >
                  {value}
                </span>
              </div>
              {idx < STAGE_DEFS.length - 1 && (
                <ChevronRight className="h-3 w-3 text-[#3b494b]" strokeWidth={2} />
              )}
            </div>
          );
        })}
      </div>

      {/* Shortlist */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="label-caps text-[#b9cacb]">Execution Shortlist</span>
          <span className="text-[10px] text-[#849495] mono-metric">
            cycle {data?.pipeline?.cycle_id?.slice(0, 8) ?? "—"}
          </span>
        </div>

        {loading ? (
          <p className="text-[11px] text-[#849495]">Loading rankings…</p>
        ) : shortlist.length === 0 ? (
          <div className="rounded-md border border-white/[0.06] bg-black/20 px-3 py-2">
            <p className="text-[11px] text-[#b9cacb]">
              No execution shortlist yet. Cached symbols are visible; paper entries still require fresh candles,
              fresh quotes, positive edge, and risk cage approval during the tick.
            </p>
            {blockers.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {blockers.map(([key, value]) => (
                  <span
                    key={key}
                    className="rounded border border-amber-300/20 bg-amber-300/10 px-2 py-0.5 text-[10px] text-amber-200"
                  >
                    {humanizeBlocker(key)}: {Number(value)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {shortlist.map((s) => (
              <li
                key={s.symbol}
                className="flex items-center gap-3 rounded-md border border-white/[0.05] bg-white/[0.02] px-3 py-2"
              >
                <AssetIcon symbol={s.symbol} size="sm" />
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-semibold text-[#e3e2e8] truncate">
                    {s.symbol}
                  </p>
                  <p className="text-[10px] text-[#849495] mono-metric">
                    {s.price !== undefined ? `$${s.price.toFixed(4)}` : "—"}
                    {s.spread_bps !== undefined && ` · spread ${s.spread_bps.toFixed(1)}bps`}
                  </p>
                </div>
                <div className="text-right">
                  <p
                    className="mono-metric text-[14px] font-bold"
                    style={{ color: "#00dbe9" }}
                  >
                    {(s.universe_rank_score * 100).toFixed(0)}
                  </p>
                  <p className="text-[9px] text-[#849495] label-caps">rank score</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </GlassPanel>
  );
}
