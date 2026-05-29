"use client";

import { useCallback, useEffect, useState } from "react";
import { Radar, ChevronRight } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { apiGet } from "@/lib/apiClient";

type EligibleRow = {
  symbol: string;
  trade_quality_score?: number;
  universe_rank_score?: number;
  stop_loss?: number;
  take_profit?: number;
  pattern_name?: string;
};

type Payload = {
  status: string;
  answer?: string;
  block_breakdown?: Record<string, number>;
  counts?: Record<string, number>;
  eligible_trades?: EligibleRow[];
};

const STAGE_DEFS = [
  { key: "available", label: "Available", color: "#849495" },
  { key: "cached", label: "Cached", color: "#b9cacb" },
  { key: "fresh", label: "Fresh", color: "#c8f3f5" },
  { key: "eligible", label: "Eligible", color: "#00dbe9" },
  { key: "to_trade", label: "To trade", color: "#00FF66" },
] as const;

function humanizeBlocker(key: string): string {
  return key.replace(/_/g, " ");
}

function symbolKey(symbol: string): string {
  return String(symbol || "").toUpperCase().replace(/[/-]/g, "");
}

function dedupeBySymbol(rows: EligibleRow[]): EligibleRow[] {
  const best = new Map<string, EligibleRow>();
  for (const row of rows.filter((r) => r.symbol)) {
    const key = symbolKey(row.symbol);
    const prev = best.get(key);
    const prevScore = Number(prev?.trade_quality_score ?? prev?.universe_rank_score ?? 0);
    const nextScore = Number(row.trade_quality_score ?? row.universe_rank_score ?? 0);
    if (!prev || nextScore >= prevScore) best.set(key, row);
  }
  return Array.from(best.values());
}

/** Compact radar strip — used on dashboards that embed funnel without full Universe page. */
export function UniverseRadarFunnel() {
  const [data, setData] = useState<Payload | null>(null);
  const [eligible, setEligible] = useState<EligibleRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const timeoutMs = 5000;
    const [radarRes, eligibleRes] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/universe/radar", { timeoutMs }),
      apiGet<Record<string, unknown>>("/api/universe/eligible-trades", { timeoutMs }),
    ]);
    const radarData = radarRes.ok ? radarRes.data : null;
    const eligibleData = eligibleRes.ok ? eligibleRes.data : null;
    const radarFunnel = (radarData?.funnel ?? {}) as Record<string, number>;
    const radarCounts = (radarData?.counts ?? {}) as Record<string, number>;
    const rows = dedupeBySymbol((eligibleData?.eligible_trades ?? eligibleData?.shortlist ?? []) as EligibleRow[]);

    setEligible(rows);
    setData({
      status: String(eligibleData?.status ?? radarData?.status ?? "ok"),
      answer: String(
        eligibleData?.answer ??
          `${rows.length} eligible — agent trades all with pattern TP/SL each cycle.`
      ),
      block_breakdown:
        (eligibleData?.no_trade_reason_breakdown as Record<string, number>) ??
        (radarData?.block_breakdown as Record<string, number>) ??
        {},
      counts: {
        available: Number(radarFunnel.available ?? radarCounts.available_usd_pairs ?? 0),
        cached: Number(radarFunnel.cached ?? radarCounts.cached_usd_pairs ?? 0),
        fresh: Number(radarFunnel.fresh ?? radarCounts.fresh ?? 0),
        eligible: Math.max(Number(radarFunnel.eligible ?? 0), rows.length),
        to_trade: rows.length,
      },
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const funnel = data?.counts ?? {};
  const blockers = Object.entries(data?.block_breakdown ?? {})
    .filter(([, value]) => Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 4);

  return (
    <GlassPanel title="Universe Radar" icon={<Radar className="h-4 w-4" style={{ color: "#00dbe9" }} />}>
      <p className="text-[11px] text-[#b9cacb] mb-2">
        Full scan — no shortlist cap — every eligible symbol gets paper entry with TP/SL bands.
      </p>
      {data?.answer && <p className="text-[10px] text-slate-500 mb-3">{data.answer.slice(0, 280)}</p>}

      <div className="flex items-center gap-1.5 flex-wrap mb-4">
        {STAGE_DEFS.map((stage, idx) => (
          <div key={stage.key} className="flex items-center gap-1.5">
            <div
              className="px-2.5 py-1 rounded-md border flex items-center gap-1.5"
              style={{ borderColor: `${stage.color}55`, background: `${stage.color}0d` }}
            >
              <span className="label-caps" style={{ color: stage.color }}>
                {stage.label}
              </span>
              <span className="mono-metric text-[11px] font-bold" style={{ color: stage.color }}>
                {loading ? "…" : funnel[stage.key] ?? 0}
              </span>
            </div>
            {idx < STAGE_DEFS.length - 1 && <ChevronRight className="h-3 w-3 text-[#3b494b]" strokeWidth={2} />}
          </div>
        ))}
      </div>

      {eligible.length === 0 ? (
        <div className="rounded-md border border-white/[0.06] bg-black/20 px-3 py-2">
          <p className="text-[11px] text-[#b9cacb]">No eligible symbols this scan.</p>
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
        <ul className="space-y-1 max-h-[180px] overflow-y-auto">
          {eligible.slice(0, 12).map((s) => (
            <li key={s.symbol} className="text-[11px] flex justify-between gap-2 text-white border-b border-white/5 py-1">
              <TickerSymbol symbol={s.symbol} size="sm" labelClassName="text-[11px] text-white" />
              <span className="text-hive-cyan mono-metric">
                Q{(((s.trade_quality_score ?? s.universe_rank_score ?? 0) as number) * 100).toFixed(0)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
