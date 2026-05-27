"use client";

import { useCallback, useEffect, useState } from "react";
import { Radar, ChevronRight } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { AssetIcon } from "@/components/ui/AssetIcon";
import { apiGet } from "@/lib/apiClient";

type Funnel = {
  available: number;
  cached: number;
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

const STAGE_DEFS = [
  { key: "available" as const, label: "Available", color: "#849495" },
  { key: "cached" as const, label: "Cached", color: "#b9cacb" },
  { key: "eligible" as const, label: "Eligible", color: "#00dbe9" },
  { key: "ranked" as const, label: "Ranked", color: "#00f0ff" },
  { key: "execution_shortlist" as const, label: "Shortlist", color: "#00FF66" },
];

export function UniverseRadarFunnel() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await apiGet<Payload>("/api/universe/radar");
    if (r.ok && r.data) setData(r.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const funnel = data?.pipeline?.funnel ?? (data?.counts
    ? {
        available: data.counts.available_usd_pairs ?? 0,
        cached: data.counts.available_usd_pairs ?? 0,
        eligible: data.counts.eligible ?? 0,
        ranked: data.counts.ranked ?? 0,
        execution_shortlist: data.counts.execution_shortlist ?? 0,
      }
    : undefined);
  const shortlist =
    (data?.pipeline?.shortlist as Shortlist[]) ??
    ((data as { execution_shortlist?: Shortlist[] })?.execution_shortlist ?? []);

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
          <p className="text-[11px] text-[#849495]">
            No symbols passed the ranking gate this cycle.
          </p>
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
