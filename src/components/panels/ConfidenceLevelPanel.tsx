"use client";

import { useCallback, useEffect, useState } from "react";
import { Gauge } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type DimCard = {
  key: string;
  title: string;
  scoreKey: string;
  fallback?: number;
};

const CARDS: DimCard[] = [
  { key: "overall", title: "Overall", scoreKey: "overall" },
  { key: "strategy", title: "Strategy", scoreKey: "strategy_validation" },
  { key: "symbol", title: "Symbol", scoreKey: "trade_performance" },
  { key: "market_regime", title: "Market Regime", scoreKey: "market_regime_confidence" },
  { key: "execution", title: "Execution", scoreKey: "execution_quality" },
  { key: "risk", title: "Risk", scoreKey: "risk_discipline" },
  { key: "data_quality", title: "Data Quality", scoreKey: "data_quality" },
  { key: "broker", title: "Broker Compatibility", scoreKey: "broker_compatibility" },
];

export function ConfidenceLevelPanel() {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [byStrategy, setByStrategy] = useState<Record<string, unknown>[]>([]);

  const load = useCallback(async () => {
    const [s, st] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/confidence/summary"),
      apiGet<{ strategies?: Record<string, unknown>[] }>("/api/confidence/by-strategy"),
    ]);
    if (s.ok) setSummary(s.data);
    if (st.ok) setByStrategy(st.data?.strategies || []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dims = (summary?.dimensions as Record<string, { score?: number; label?: string; evidence?: string[] }>) || {};

  function scoreFor(card: DimCard): { score: number; label: string; evidence: string[] } {
    if (card.key === "overall") {
      return {
        score: Number(summary?.overall ?? 0),
        label: String(summary?.overall_label ?? "—"),
        evidence: [String(summary?.interpretation || "")],
      };
    }
    if (card.key === "market_regime") {
      const s = Number(summary?.market_regime_confidence ?? 0);
      return { score: s, label: s >= 60 ? "Developing" : "Weak", evidence: [] };
    }
    const d = dims[card.scoreKey];
    if (d) {
      return {
        score: Number(d.score ?? 0),
        label: String(d.label ?? "—"),
        evidence: (d.evidence as string[]) || [],
      };
    }
    return { score: 0, label: "—", evidence: [] };
  }

  return (
    <GlassPanel title="Confidence Level" icon={<Gauge className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Evidence-based scores for learning — not permission to enable live trading. Live unlock requires operator
        checklist only.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        {CARDS.map((card) => {
          const { score, label, evidence } = scoreFor(card);
          return (
            <div key={card.key} className="rounded-lg border border-white/10 bg-black/20 p-3">
              <div className="text-[10px] text-slate-500">{card.title}</div>
              <div className="text-xl font-bold text-cyan-300">{score.toFixed(0)}</div>
              <div className="text-[9px] text-slate-400">{label}</div>
              {evidence[0] && <p className="text-[8px] text-slate-500 mt-1 line-clamp-2">{evidence[0]}</p>}
            </div>
          );
        })}
      </div>

      {byStrategy.length > 0 && (
        <div>
          <h3 className="text-[10px] font-semibold text-slate-400 mb-2">By strategy</h3>
          <ul className="text-[9px] text-slate-400 space-y-1 max-h-32 overflow-y-auto">
            {byStrategy.slice(0, 10).map((s) => (
              <li key={String(s.strategy_id)}>
                {String(s.strategy_id)} — {String(s.score)} ({String(s.label)}) · {String(s.closed_trades)} closed
              </li>
            ))}
          </ul>
        </div>
      )}
    </GlassPanel>
  );
}
