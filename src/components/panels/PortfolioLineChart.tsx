"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LineChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { apiGet } from "@/lib/apiClient";
import { formatDisplaySymbol } from "@/lib/assetIcons";

type Point = { time: import("lightweight-charts").UTCTimestamp; value: number };

type Candle = { time: number; open?: number; high?: number; low?: number; close: number; volume?: number };

type CandlePayload = {
  status?: string;
  candles?: Candle[];
  bar_count?: number;
  last_close?: number;
  message?: string | null;
  source?: string;
};

type ChartContextPayload = {
  overlay_summary?: {
    entry?: number;
    stop_loss?: number;
    take_profit?: number;
  };
  ai_narrative?: string;
};

type LoadedSource = "tradingview_cache" | "market_data_ohlc" | "none";

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

  // Buffer the most recently fetched data so that if the chart finishes
  // initialising AFTER the fetch completes, we still draw the line. This
  // was the root cause of the chart staying blank — the async createChart()
  // promise resolved after load(), and seriesRef.current?.setData(data) was
  // a no-op.
  const pendingDataRef = useRef<Point[] | null>(null);
  const pendingOverlayRef = useRef<ChartContextPayload["overlay_summary"] | null>(null);

  const [symbol, setSymbol] = useState(defaultSymbol || symbols[0] || "BTC/USD");
  const [loading, setLoading] = useState(false);
  const [emptyMessage, setEmptyMessage] = useState<string | null>(null);
  const [chartReady, setChartReady] = useState(false);
  const [summary, setSummary] = useState<ChartContextPayload["overlay_summary"]>();
  const [note, setNote] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ barCount: number; lastClose: number | null; source: LoadedSource }>({
    barCount: 0,
    lastClose: null,
    source: "none",
  });

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

  const drawOverlay = useCallback((ov: ChartContextPayload["overlay_summary"] | null) => {
    clearLines();
    if (!seriesRef.current || !ov) return;
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
  }, []);

  const applyDataToChart = useCallback(
    (data: Point[], overlay: ChartContextPayload["overlay_summary"] | null) => {
      pendingDataRef.current = data;
      pendingOverlayRef.current = overlay;
      if (seriesRef.current) {
        seriesRef.current.setData(data);
        chartRef.current?.timeScale().fitContent();
        drawOverlay(overlay);
      }
    },
    [drawOverlay],
  );

  const candlesFromPayload = (payload: CandlePayload | null | undefined): Candle[] => {
    if (!payload) return [];
    const list = Array.isArray(payload.candles) ? payload.candles : [];
    return list.filter((c) => typeof c?.time === "number" && typeof c?.close === "number");
  };

  const load = useCallback(async () => {
    if (!symbol) return;
    setLoading(true);
    setEmptyMessage(null);

    // 1. Primary: TradingView cached chart endpoint (same DB-cached HistoricalBar rows).
    // 2. Fallback: market-data/ohlc (DB-first, refresh from Alpaca only if allowed).
    // 3. chart-context: best-effort overlay (entry/stop/target).
    const [tvRes, ctxRes] = await Promise.all([
      apiGet<CandlePayload>(
        `/api/tradingview/chart?symbol=${encodeURIComponent(symbol)}&timeframe=5Min&limit=120`,
        { timeoutMs: 8000 },
      ),
      apiGet<ChartContextPayload>(
        `/api/market-data/chart-context?symbol=${encodeURIComponent(symbol)}`,
        { timeoutMs: 8000 },
      ),
    ]);

    let candles = tvRes.ok ? candlesFromPayload(tvRes.data) : [];
    let source: LoadedSource = candles.length ? "tradingview_cache" : "none";

    if (!candles.length) {
      const fallback = await apiGet<CandlePayload>(
        `/api/market-data/ohlc?symbol=${encodeURIComponent(symbol)}&timeframe=5Min&limit=120`,
        { timeoutMs: 8000 },
      );
      if (fallback.ok) {
        candles = candlesFromPayload(fallback.data);
        if (candles.length) source = "market_data_ohlc";
      }
    }

    const ov = ctxRes.ok ? ctxRes.data?.overlay_summary ?? null : null;
    setSummary(ov ?? undefined);
    setNote(ctxRes.ok ? ctxRes.data?.ai_narrative ?? null : null);

    if (!candles.length) {
      pendingDataRef.current = [];
      pendingOverlayRef.current = ov;
      if (seriesRef.current) {
        seriesRef.current.setData([]);
        clearLines();
      }
      setMeta({ barCount: 0, lastClose: null, source: "none" });
      setEmptyMessage("No cached bars yet for this position.");
      setLoading(false);
      return;
    }

    const data: Point[] = candles.map((c) => ({
      time: c.time as import("lightweight-charts").UTCTimestamp,
      value: c.close,
    }));
    const lastClose = data[data.length - 1]?.value ?? null;
    setMeta({ barCount: data.length, lastClose, source });
    applyDataToChart(data, ov);
    setLoading(false);
  }, [symbol, applyDataToChart]);

  useEffect(() => {
    if (defaultSymbol) setSymbol(formatDisplaySymbol(defaultSymbol));
  }, [defaultSymbol]);

  // Chart lifecycle: create once, flush any pending data after init.
  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    let cleanup: (() => void) | undefined;

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
      setChartReady(true);

      // Flush any data that arrived BEFORE the chart was ready.
      const pendingData = pendingDataRef.current;
      const pendingOverlay = pendingOverlayRef.current;
      if (pendingData && pendingData.length) {
        series.setData(pendingData);
        chart.timeScale().fitContent();
      }
      if (pendingOverlay) {
        drawOverlay(pendingOverlay);
      }

      const ro = new ResizeObserver(() => {
        if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
      });
      ro.observe(containerRef.current);
      cleanup = () => {
        ro.disconnect();
        try {
          chart.remove();
        } catch {
          /* ignore double-dispose */
        }
      };
    })();

    return () => {
      disposed = true;
      try {
        clearLines();
      } catch {
        /* ignore */
      }
      if (cleanup) cleanup();
      chartRef.current = null;
      seriesRef.current = null;
      setChartReady(false);
    };
  }, [drawOverlay]);

  // Fetch whenever the selected symbol changes; the chart may not yet be ready
  // — pendingDataRef bridges the gap.
  useEffect(() => {
    load();
  }, [load]);

  const sourceLabel = (() => {
    if (meta.source === "tradingview_cache") return "TradingView cache";
    if (meta.source === "market_data_ohlc") return "Market data OHLC";
    return null;
  })();

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
        {meta.barCount > 0 && (
          <span className="text-[10px] text-slate-500 mono-metric">
            {meta.barCount} bars
            {meta.lastClose != null && (
              <>
                {" · last "}
                <span className="text-slate-300">{meta.lastClose.toFixed(4)}</span>
              </>
            )}
            {sourceLabel && <span className="text-slate-600"> · {sourceLabel}</span>}
          </span>
        )}
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
      {loading && <p className="text-[10px] text-slate-500 mb-1">Loading price history…</p>}
      {!loading && emptyMessage && (
        <p className="text-[10px] text-amber-300 mb-1">{emptyMessage}</p>
      )}
      {!loading && !chartReady && !emptyMessage && (
        <p className="text-[10px] text-slate-500 mb-1">Initialising chart…</p>
      )}
      <div ref={containerRef} className="w-full rounded-lg border border-white/[0.06] overflow-hidden" />
    </GlassPanel>
  );
}
