"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LineChart } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

type TradingViewStatus = {
  mode?: string;
  execution_allowed?: boolean;
  execution_blocked_reason?: string;
  latest_event?: Record<string, unknown> | null;
};

type CachedCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

type CachedChart = {
  status?: string;
  source?: string;
  symbol?: string;
  timeframe?: string;
  bar_count?: number;
  last_close?: number | null;
  candles?: CachedCandle[];
  message?: string | null;
};

const SYMBOLS = [
  { label: "BTC/USD", value: "BTC/USD", tv: "BITSTAMP:BTCUSD" },
  { label: "ETH/USD", value: "ETH/USD", tv: "BITSTAMP:ETHUSD" },
  { label: "SOL/USD", value: "SOL/USD", tv: "COINBASE:SOLUSD" },
  { label: "DOGE/USD", value: "DOGE/USD", tv: "COINBASE:DOGEUSD" },
  { label: "LTC/USD", value: "LTC/USD", tv: "COINBASE:LTCUSD" },
];

function tradingViewUrl(tvSymbol: string): string {
  const params = new URLSearchParams({
    symbol: tvSymbol,
    interval: "5",
    theme: "dark",
    style: "1",
    timezone: "Etc/UTC",
    withdateranges: "1",
    hide_side_toolbar: "0",
    allow_symbol_change: "1",
    save_image: "0",
    locale: "en",
  });
  return `https://s.tradingview.com/widgetembed/?${params.toString()}`;
}

function LocalCachedChart({ candles }: { candles: CachedCandle[] }) {
  const points = useMemo(() => {
    if (!candles.length) return "";
    const width = 720;
    const height = 180;
    const values = candles.map((c) => Number(c.close)).filter(Number.isFinite);
    if (!values.length) return "";
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(max - min, 0.000001);
    return candles
      .map((c, i) => {
        const x = candles.length === 1 ? width / 2 : (i / (candles.length - 1)) * width;
        const y = height - ((Number(c.close) - min) / span) * (height - 16) - 8;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [candles]);

  if (!candles.length) return null;

  const last = candles[candles.length - 1];
  const first = candles[0];
  const up = Number(last.close) >= Number(first.close);

  return (
    <div className="rounded-xl border border-white/10 bg-black/30 p-3">
      <div className="mb-2 flex items-center justify-between text-[10px] text-slate-500">
        <span>Local cached fallback</span>
        <span className={up ? "text-emerald-300" : "text-rose-300"}>
          Last {Number(last.close).toFixed(4)}
        </span>
      </div>
      <svg viewBox="0 0 720 180" className="h-[180px] w-full overflow-visible rounded-lg bg-[#05070d]">
        <defs>
          <linearGradient id="tvFallbackFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={up ? "#22c55e" : "#ef4444"} stopOpacity="0.35" />
            <stop offset="100%" stopColor={up ? "#22c55e" : "#ef4444"} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((i) => (
          <line key={i} x1="0" x2="720" y1={45 * i} y2={45 * i} stroke="rgba(148,163,184,.14)" />
        ))}
        <polyline points={`0,180 ${points} 720,180`} fill="url(#tvFallbackFill)" stroke="none" />
        <polyline
          points={points}
          fill="none"
          stroke={up ? "#22c55e" : "#ef4444"}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.5"
        />
      </svg>
    </div>
  );
}

export function TradingViewIntegrationPanel() {
  const [status, setStatus] = useState<TradingViewStatus | null>(null);
  const [overlays, setOverlays] = useState<Record<string, unknown>[]>([]);
  const [symbol, setSymbol] = useState("BTC/USD");
  const [chart, setChart] = useState<CachedChart | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  const selected = SYMBOLS.find((s) => s.value === symbol) ?? SYMBOLS[0];
  const widgetUrl = tradingViewUrl(selected.tv);

  const load = useCallback(async () => {
    const [st, ov, ch] = await Promise.all([
      apiGet<TradingViewStatus>("/api/tradingview/status"),
      apiGet<{ overlays?: Record<string, unknown>[] }>("/api/tradingview/overlays"),
      apiGet<CachedChart>(`/api/tradingview/chart?symbol=${encodeURIComponent(symbol)}&timeframe=5Min&limit=120`, {
        timeoutMs: 2500,
      }),
    ]);
    if (st.ok) setStatus(st.data);
    if (ov.ok) setOverlays(ov.data?.overlays || []);
    if (ch.ok) {
      setChart(ch.data);
      setChartError(null);
    } else {
      setChart(null);
      setChartError(ch.error || "Cached chart unavailable.");
    }
  }, [symbol]);

  useEffect(() => {
    load();
  }, [load]);

  const candles = chart?.candles ?? [];

  return (
    <GlassPanel title="TradingView Wrapper" icon={<LineChart className="h-4 w-4" />}>
      <p className="mb-3 text-[10px] text-slate-500">
        Display only. Execution blocked. Orders can only go through Caged Hive execution cage.
      </p>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <label className="text-[10px] uppercase text-slate-500" htmlFor="tv-symbol">
            Symbol
          </label>
          <select
            id="tv-symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-xs text-slate-100"
          >
            {SYMBOLS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-[10px] text-emerald-200">
          Display-only / execution blocked
        </span>
      </div>

      <div className="overflow-hidden rounded-xl border border-hive-cyan/20 bg-black/40">
        <iframe
          key={selected.tv}
          title={`TradingView ${selected.label}`}
          src={widgetUrl}
          className="h-[420px] w-full"
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
        />
      </div>

      <div className="mt-3">
        {candles.length ? (
          <LocalCachedChart candles={candles} />
        ) : (
          <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-[10px] text-slate-500">
            {chartError || chart?.message || "TradingView widget is primary. No cached bars found for local fallback."}
          </div>
        )}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Mode</p>
          <p className="text-slate-200">{status?.mode ?? "display_only"}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Execution</p>
          <p className="text-emerald-300">{status?.execution_allowed ? "Unexpected" : "Blocked"}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Cached bars</p>
          <p className="text-slate-200">{chart?.bar_count ?? 0}</p>
        </div>
      </div>
      <p className="mt-2 text-[10px] text-slate-500">
        Block reason: {status?.execution_blocked_reason ?? "display_only_execution_blocked"}
      </p>
      <ul className="mt-3 max-h-56 space-y-2 overflow-auto text-[10px] text-slate-400">
        {!overlays.length ? <li>No TradingView events yet.</li> : null}
        {overlays.slice(0, 12).map((o, i) => (
          <li key={String(o.id ?? i)} className="rounded border border-white/10 p-2">
            {String(o.event_type ?? "signal")} -{" "}
            {String((o.mapped_signal as Record<string, unknown> | undefined)?.symbol ?? "unknown")}
            <p className="text-slate-500">{String(o.execution_blocked_reason ?? "display_only_execution_blocked")}</p>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}
