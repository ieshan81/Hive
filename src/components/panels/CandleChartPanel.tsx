"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CandlestickChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
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

type ChartMarker = {
  time: number;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text?: string;
};

type PriceLine = {
  price: number;
  color: string;
  title: string;
  lineStyle?: number;
  axisLabelVisible?: boolean;
  kind?: string;
};

type OverlaySummary = {
  entry?: number;
  stop_loss?: number;
  take_profit?: number;
  risk_reward?: number;
};

type ChartContextPayload = {
  status: string;
  markers?: ChartMarker[];
  price_lines?: PriceLine[];
  overlay_summary?: OverlaySummary;
  ai_narrative?: string;
};

function OverlayLegend({ summary, lines }: { summary?: OverlaySummary; lines?: PriceLine[] }) {
  const items =
    summary && (summary.entry || summary.stop_loss || summary.take_profit)
      ? [
          summary.entry != null ? { label: "Entry", value: summary.entry, color: "#00dbe9" } : null,
          summary.stop_loss != null ? { label: "Stop", value: summary.stop_loss, color: "#EF4444" } : null,
          summary.take_profit != null ? { label: "Target", value: summary.take_profit, color: "#00FF66" } : null,
        ].filter(Boolean)
      : (lines ?? []).map((l) => ({
          label: l.title,
          value: l.price,
          color: l.color,
        }));

  if (!items.length) return null;

  return (
    <div className="flex flex-wrap gap-2 mb-2">
      {items.map((item) => (
        <span
          key={`${item!.label}-${item!.value}`}
          className="inline-flex items-center gap-1.5 rounded border border-white/10 bg-black/30 px-2 py-1 text-[10px]"
        >
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item!.color }} />
          <span className="text-slate-400">{item!.label}</span>
          <span className="text-white mono-metric">{Number(item!.value).toFixed(4)}</span>
        </span>
      ))}
      {summary?.risk_reward != null && (
        <span className="inline-flex items-center rounded border border-violet-500/20 bg-violet-950/30 px-2 py-1 text-[10px] text-violet-200">
          R:R {summary.risk_reward}
        </span>
      )}
      <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
        <span className="h-2 w-2 rounded-full bg-[#00FF66]" /> fill
        <span className="h-2 w-2 rounded-full bg-[#a78bfa] ml-1" /> AI
      </span>
    </div>
  );
}

const DEFAULT_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"];

export function CandleChartPanel({
  defaultSymbol = "BTC/USD",
  symbolOptions,
  compact = false,
  lockSymbol = false,
  title = "Live Candles + AI brain",
}: {
  defaultSymbol?: string;
  symbolOptions?: string[];
  compact?: boolean;
  lockSymbol?: boolean;
  title?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);
  const seriesRef = useRef<ReturnType<
    ReturnType<typeof import("lightweight-charts").createChart>["addCandlestickSeries"]
  > | null>(null);
  const priceLinesRef = useRef<import("lightweight-charts").IPriceLine[]>([]);
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [timeframe, setTimeframe] = useState("5Min");
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<{ count: number; last?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [brainNote, setBrainNote] = useState<string | null>(null);
  const [overlaySummary, setOverlaySummary] = useState<OverlaySummary | undefined>();
  const [priceLines, setPriceLines] = useState<PriceLine[]>([]);

  const symbols = symbolOptions?.length ? symbolOptions : DEFAULT_SYMBOLS;

  const clearPriceLines = () => {
    for (const line of priceLinesRef.current) {
      try {
        seriesRef.current?.removePriceLine(line);
      } catch {
        /* ignore */
      }
    }
    priceLinesRef.current = [];
  };

  const applyOverlays = useCallback((ctx: ChartContextPayload | null) => {
    if (!seriesRef.current || !ctx) return;
    const markers = (ctx.markers ?? []).map((m) => ({
      time: m.time as import("lightweight-charts").UTCTimestamp,
      position: m.position,
      color: m.color,
      shape: m.shape,
      text: m.text,
    }));
    seriesRef.current.setMarkers(markers);
    clearPriceLines();
    for (const pl of ctx.price_lines ?? []) {
      const line = seriesRef.current.createPriceLine({
        price: pl.price,
        color: pl.color,
        title: pl.title,
        lineWidth: pl.kind === "entry" ? 2 : 1,
        lineStyle: pl.lineStyle ?? 2,
        axisLabelVisible: pl.axisLabelVisible ?? false,
      });
      priceLinesRef.current.push(line);
    }
    setOverlaySummary(ctx.overlay_summary);
    setPriceLines(ctx.price_lines ?? []);
    setBrainNote(ctx.ai_narrative ?? null);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [r, ctxRes] = await Promise.all([
      apiGet<OhlcPayload>(
        `/api/market-data/ohlc?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=180`,
        { timeoutMs: 25000 }
      ),
      apiGet<ChartContextPayload>(
        `/api/market-data/chart-context?symbol=${encodeURIComponent(symbol)}`,
        { timeoutMs: 12000 }
      ),
    ]);
    if (!r.ok || !r.data || r.data.status !== "ok" || !r.data.candles?.length) {
      setError(r.data?.message || r.error || "No candle data");
      seriesRef.current?.setData([]);
      seriesRef.current?.setMarkers([]);
      clearPriceLines();
      setMeta(null);
      setBrainNote(null);
      setOverlaySummary(undefined);
      setPriceLines([]);
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
    if (ctxRes.ok && ctxRes.data) applyOverlays(ctxRes.data);
    else setBrainNote("AI trade markers load when backend chart-context is available.");
    setLoading(false);
  }, [symbol, timeframe, applyOverlays]);

  useEffect(() => {
    setSymbol(defaultSymbol);
  }, [defaultSymbol]);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    (async () => {
      const { createChart, ColorType } = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;
      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: compact ? 220 : 360,
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
      clearPriceLines();
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
    <GlassPanel title={title} icon={<CandlestickChart className="h-4 w-4 text-hive-cyan" />}>
      {!compact && (
        <p className="text-[10px] text-slate-500 mb-2">
          TradingView Lightweight Charts · arrows = fills · purple = AI signal · lines = SL/TP bands
        </p>
      )}
      <div className="flex flex-wrap gap-2 mb-2 items-center">
        {lockSymbol ? (
          <TickerSymbol symbol={symbol} size="sm" labelClassName="text-[11px] font-semibold text-white" />
        ) : (
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 text-slate-200"
          >
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
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
      {brainNote && (
        <p className="text-[10px] text-violet-200/90 mb-2 border border-violet-500/20 rounded px-2 py-1 bg-violet-950/20">
          {brainNote}
        </p>
      )}
      <OverlayLegend summary={overlaySummary} lines={priceLines} />
      {loading && <p className="text-[10px] text-slate-500 mb-1">Loading candles…</p>}
      {error && <p className="text-[10px] text-amber-400 mb-1">{error}</p>}
      <div ref={containerRef} className="w-full rounded-lg border border-white/[0.06] overflow-hidden" />
    </GlassPanel>
  );
}
