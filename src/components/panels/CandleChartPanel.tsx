"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CandlestickChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type Candle = { time: number; open: number; high: number; low: number; close: number };

type OhlcPayload = {
  status: string;
  symbol: string;
  timeframe: string;
  candles: Candle[];
  last_close?: number;
  message?: string;
};

const DEFAULT_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"];

export function CandleChartPanel({ defaultSymbol = "BTC/USD" }: { defaultSymbol?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);
  const seriesRef = useRef<ReturnType<
    ReturnType<typeof import("lightweight-charts").createChart>["addCandlestickSeries"]
  > | null>(null);
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [timeframe, setTimeframe] = useState("5Min");
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<{ count: number; last?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const r = await apiGet<OhlcPayload>(
      `/api/market-data/ohlc?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=180`,
      { timeoutMs: 25000 }
    );
    if (!r.ok || !r.data || r.data.status !== "ok" || !r.data.candles?.length) {
      setError(r.data?.message || r.error || "No candle data");
      seriesRef.current?.setData([]);
      setMeta(null);
      setLoading(false);
      return;
    }
    const candles = r.data.candles.map((c) => ({
      time: c.time as import("lightweight-charts").UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    seriesRef.current?.setData(candles);
    chartRef.current?.timeScale().fitContent();
    setMeta({ count: candles.length, last: r.data.last_close });
    setLoading(false);
  }, [symbol, timeframe]);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    (async () => {
      const { createChart, ColorType } = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;
      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: 320,
        layout: {
          background: { type: ColorType.Solid, color: "#0a0b0f" },
          textColor: "#b9cacb",
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
        timeScale: { borderColor: "rgba(255,255,255,0.08)" },
      });
      const series = chart.addCandlestickSeries({
        upColor: "#00FF66",
        downColor: "#EF4444",
        borderVisible: false,
        wickUpColor: "#00FF66",
        wickDownColor: "#EF4444",
      });
      chartRef.current = chart;
      seriesRef.current = series;
      const ro = new ResizeObserver(() => {
        if (containerRef.current) {
          chart.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      ro.observe(containerRef.current);
      return () => {
        ro.disconnect();
        chart.remove();
      };
    })();
    return () => {
      disposed = true;
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 45000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <GlassPanel title="Live Candles" icon={<CandlestickChart className="h-4 w-4 text-hive-cyan" />}>
      <p className="text-[10px] text-slate-500 mb-2">
        TradingView Lightweight Charts · Alpaca/DB OHLC · updates every 45s
      </p>
      <div className="flex flex-wrap gap-2 mb-2 items-center">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200"
        >
          {DEFAULT_SYMBOLS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          className="text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200"
        >
          <option value="1Min">1Min</option>
          <option value="5Min">5Min</option>
          <option value="15Min">15Min</option>
          <option value="1Hour">1Hour</option>
        </select>
        <button type="button" onClick={load} className="text-[10px] text-hive-cyan px-2">
          Refresh
        </button>
        {meta && (
          <span className="text-[10px] text-slate-500 mono-metric">
            {meta.count} bars · last {meta.last?.toFixed(4) ?? "—"}
          </span>
        )}
      </div>
      {loading && <p className="text-[10px] text-slate-500 mb-1">Loading candles…</p>}
      {error && <p className="text-[10px] text-amber-400 mb-1">{error}</p>}
      <div ref={containerRef} className="w-full rounded-lg border border-white/[0.06] overflow-hidden" />
    </GlassPanel>
  );
}
