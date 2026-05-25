"use client";

import { useCallback, useEffect, useState } from "react";
import { CandlestickChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPost } from "@/lib/apiClient";

interface Annotation {
  type: string;
  level: number;
  reason: string;
  timeframe: string;
  confidence: number;
  invalidation_level: number;
  source_bars: number;
}

export function CandleLabPanel() {
  const [symbol, setSymbol] = useState("DOGE/USD");
  const [analysis, setAnalysis] = useState<{
    status?: string;
    annotations?: Annotation[];
    indicators?: Record<string, unknown>;
    patterns?: { patterns?: unknown[] };
    bar_count?: number;
    last_price?: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await apiPost<typeof analysis>("/api/candle-lab/analyze", {
      symbol,
      timeframe: "5Min",
    });
    if (r.ok && r.data) setAnalysis(r.data as typeof analysis);
    setLoading(false);
  }, [symbol]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <GlassPanel title="Candle Lab" icon={<CandlestickChart className="h-4 w-4" />}>
      <p className="text-[11px] text-amber-300/90 mb-2 font-medium">
        Analysis only — no trade is placed from this screen.
      </p>
      <div className="flex gap-2 mb-2">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200"
        />
        <button type="button" onClick={load} className="text-[10px] text-hive-cyan">
          Analyze
        </button>
      </div>
      {loading && <p className="text-[10px] text-slate-500">Loading bars…</p>}
      {analysis?.status === "empty" && (
        <p className="text-[10px] text-amber-400">No bars — fetch historical data first.</p>
      )}
      {analysis && analysis.status === "ok" && (
        <>
          <p className="text-[10px] text-slate-400 mb-2">
            {analysis.bar_count} bars · last {analysis.last_price} · RSI{" "}
            {String((analysis.indicators as Record<string, unknown>)?.rsi_14 ?? "—")}
          </p>
          <ul className="space-y-2 max-h-[280px] overflow-y-auto">
            {(analysis.annotations || []).map((a, i) => (
              <li key={i} className="text-[9px] border border-white/5 rounded p-2 bg-white/5">
                <span className="text-cyan-300 font-semibold">{a.type}</span> @ {a.level}
                <p className="text-slate-400 mt-0.5">{a.reason}</p>
                <p className="text-slate-500 text-[9px]">
                  Timeframe: {a.timeframe} · Confidence: {a.confidence} · Invalidation:{" "}
                  {a.invalidation_level} · Source bars: {a.source_bars}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </GlassPanel>
  );
}
