"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LineChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { apiGet } from "@/lib/apiClient";
import { formatDisplaySymbol } from "@/lib/assetIcons";

type Point = { time: import("lightweight-charts").UTCTimestamp; value: number };

type OhlcPayload = {
  status: string;
  candles: Array<{ time: number; close: number }>;
  last_close?: number;
  message?: string;
};

type ChartContextPayload = {
  overlay_summary?: {
    entry?: number;
    stop_loss?: number;
    take_profit?: number;
  };
  ai_narrative?: string;
};

/** Fast single-symbol line chart for portfolio (one panel, symbol picker). */
export function PortfolioLineChart({
  symbols,
  defaultSymbol,
}: {
  symbols: string[];
  defaultSymbol?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);
  const seriesRef = useRef<ReturnType<
    ReturnType<typeof import("lightweight-charts").createChart>["addLineSeries"]
  > | null>(null);
  const priceLinesRef = useRef<import("lightweight-charts").IPriceLine[]>([]);
  const [symbol, setSymbol] = useState(defaultSymbol || symbols[0] || "BTC/USD");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ChartContextPayload["overlay_summary"]>();
  const [note, setNote] = useState<string | null>(null);

  const options = symbols.length ? symbols.map(formatDisplaySymbol) : ["BTC/USD"];

  const clearLines = () => {
    for (const line of priceLinesRef.current) {
      try {
        seriesRef.current?.removePriceLine(line);
      } catch {
        /* ignore */
      }
    }
    priceLinesRef.current = [];
  };

  const load = useCallback(async () => {
    if (!symbol) return;
    setLoading(true);
    setError(null);
    const [ohlc, ctx] = await Promise.all([
      apiGet<OhlcPayload>(
        `/api/market-data/ohlc?symbol=${encodeURIComponent(symbol)}&timeframe=5Min&limit=72`,
        { timeoutMs: 8000 }
      ),
      apiGet<ChartContextPayload>(
        `/api/market-data/chart-context?symbol=${encodeURIComponent(symbol)}`,
        { timeoutMs: 8000 }
      ),
    ]);
    if (!ohlc.ok || !ohlc.data?.candles?.length) {
      setError(ohlc.data?.message || ohlc.error || "No price data");
      seriesRef.current?.setData([]);
      clearLines();
      setLoading(false);
      return;
    }
    const data: Point[] = ohlc.data.candles.map((c) => ({
      time: c.time as import("lightweight-charts").UTCTimestamp,
      value: c.close,
    }));
    seriesRef.current?.setData(data);
    chartRef.current?.timeScale().fitContent();
    clearLines();
    const ov = ctx.ok ? ctx.data?.overlay_summary : undefined;
    setSummary(ov);
    setNote(ctx.ok ? ctx.data?.ai_narrative ?? null : null);
    if (seriesRef.current && ov) {
      const bands = [
        { price: ov.entry, color: "#00dbe9", title: "Entry" },
        { price: ov.stop_loss, color: "#EF4444", title: "Stop" },
        { price: ov.take_profit, color: "#00FF66", title: "Target" },
      ];
      for (const b of bands) {
        if (b.price == null || b.price <= 0) continue;
        const line = seriesRef.current.createPriceLine({
          price: b.price,
          color: b.color,
          title: b.title,
          lineWidth: 1,
          axisLabelVisible: false,
        });
        priceLinesRef.current.push(line);
      }
    }
    setLoading(false);
  }, [symbol]);

  useEffect(() => {
    if (defaultSymbol) setSymbol(formatDisplaySymbol(defaultSymbol));
  }, [defaultSymbol]);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    (async () => {
      const { createChart, ColorType } = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;
      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: 240,
        layout: { background: { type: ColorType.Solid, color: "#0a0b0f" }, textColor: "#b9cacb" },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
        timeScale: { borderColor: "rgba(255,255,255,0.08)" },
      });
      const series = chart.addLineSeries({ color: "#00dbe9", lineWidth: 2 });
      chartRef.current = chart;
      seriesRef.current = series;
      const ro = new ResizeObserver(() => {
        if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
      });
      ro.observe(containerRef.current);
      return () => {
        ro.disconnect();
        chart.remove();
      };
    })();
    return () => {
      disposed = true;
      clearLines();
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <GlassPanel title="Position price curve" icon={<LineChart className="h-4 w-4 text-hive-cyan" />}>
      <p className="text-[10px] text-slate-500 mb-2">
        One chart for all positions — pick a symbol. Y-axis is price per unit (USD), not account balance.
      </p>
      <div className="flex flex-wrap gap-2 mb-2 items-center">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200"
        >
          {options.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <TickerSymbol symbol={symbol} size="sm" showIcon={false} labelClassName="text-[10px] text-slate-400" />
        <button type="button" onClick={load} className="text-[10px] text-hive-cyan px-2">
          Refresh
        </button>
      </div>
      {summary && (summary.entry || summary.stop_loss || summary.take_profit) && (
        <div className="flex flex-wrap gap-2 mb-2 text-[10px]">
          {summary.entry != null && (
            <span className="text-cyan-300">Entry {summary.entry.toFixed(4)}</span>
          )}
          {summary.stop_loss != null && (
            <span className="text-red-300">Stop {summary.stop_loss.toFixed(4)}</span>
          )}
          {summary.take_profit != null && (
            <span className="text-emerald-300">Target {summary.take_profit.toFixed(4)}</span>
          )}
        </div>
      )}
      {note && <p className="text-[10px] text-violet-200/80 mb-2">{note}</p>}
      {loading && <p className="text-[10px] text-slate-500 mb-1">Loading…</p>}
      {error && <p className="text-[10px] text-amber-400 mb-1">{error}</p>}
      <div ref={containerRef} className="w-full rounded-lg border border-white/[0.06] overflow-hidden" />
    </GlassPanel>
  );
}
