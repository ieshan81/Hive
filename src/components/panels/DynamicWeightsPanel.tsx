"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPost } from "@/lib/apiClient";

type WeightsPayload = {
  status: string;
  ai_managed?: boolean;
  universe_ranking?: Record<string, number>;
  min_rank_score?: number;
  last_adjustment?: { reason?: string; updated_at?: string; changed_by?: string };
};

const LABELS: Record<string, string> = {
  w_liquidity: "Liquidity",
  w_spread: "Spread quality",
  w_volume_spike: "Volume spike",
  w_atr: "ATR / volatility",
  w_freshness: "Data freshness",
  w_cost_efficiency: "Cost efficiency",
};

export function DynamicWeightsPanel() {
  const [data, setData] = useState<WeightsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebalancing, setRebalancing] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<WeightsPayload>("/api/weights", { timeoutMs: 12000 });
    if (r.ok && r.data) setData(r.data);
    setLoading(false);
  }, []);

  const aiRebalance = async () => {
    setRebalancing(true);
    const r = await apiPost<Record<string, unknown>>("/api/weights/ai-rebalance", {
      context: { source: "push_pull_ui" },
    });
    if (r.ok && r.data) {
      const nested = r.data.weights as WeightsPayload | undefined;
      setData(nested ?? (r.data as unknown as WeightsPayload));
    }
    setRebalancing(false);
    await load();
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const weights = data?.universe_ranking ?? {};

  return (
    <GlassPanel title="AI Ranking Weights" icon={<Brain className="h-4 w-4 text-hive-cyan" />}>
      <p className="text-[11px] text-slate-400 mb-2">
        Universe funnel weights are stored in config — not hardcoded. Gemini can rebalance based on
        current shortlist health.
      </p>
      {loading ? (
        <p className="text-[10px] text-slate-500">Loading weights…</p>
      ) : (
        <>
          <p className="text-[10px] text-slate-500 mb-2">
            Min rank score: <span className="text-white">{data?.min_rank_score ?? "—"}</span>
            {data?.last_adjustment?.updated_at && (
              <>
                {" "}
                · last update {data.last_adjustment.updated_at.slice(0, 19)} (
                {data.last_adjustment.changed_by})
              </>
            )}
          </p>
          <div className="space-y-2 mb-3">
            {Object.entries(weights).map(([key, val]) => (
              <div key={key} className="flex items-center gap-2">
                <span className="text-[10px] text-slate-400 w-28 shrink-0">
                  {LABELS[key] ?? key}
                </span>
                <div className="flex-1 h-2 rounded bg-white/5 overflow-hidden">
                  <div
                    className="h-full bg-hive-cyan/70"
                    style={{ width: `${Math.min(100, Number(val) * 100)}%` }}
                  />
                </div>
                <span className="text-[10px] mono-metric text-white w-10 text-right">
                  {(Number(val) * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
          <button
            type="button"
            disabled={rebalancing}
            onClick={aiRebalance}
            className="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded border border-hive-cyan/30 text-hive-cyan hover:bg-hive-cyan/10 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${rebalancing ? "animate-spin" : ""}`} />
            {rebalancing ? "Rebalancing…" : "AI rebalance weights"}
          </button>
          {data?.last_adjustment?.reason && (
            <p className="text-[9px] text-slate-500 mt-2">{data.last_adjustment.reason}</p>
          )}
        </>
      )}
    </GlassPanel>
  );
}
