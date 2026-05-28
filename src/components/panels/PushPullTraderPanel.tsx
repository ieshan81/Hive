"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { TrendingUp } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet } from "@/lib/apiClient";
import { PushPullCandleCard, PaperOrderProofPanel } from "@/components/panels/PushPullCandleCard";

function humanize(key: string): string {
  const normalized = key.toLowerCase();
  const known: Record<string, string> = {
    data_stale: "Stale candle or quote data",
    stale_quote_after_refresh: "Quote still stale after refresh",
    quote_currency_unfunded: "Quote currency not funded",
    no_push_signal: "No push signal",
    push_below_threshold: "Push below adaptive threshold",
    ema_confirmation: "Trend confirmation weak",
    quality_below_min: "Trade quality below adaptive minimum",
    candle_quality: "Candle body too weak",
    volume_spike: "Volume impulse too weak",
    quote_fresh: "Quote too old",
    bar_fresh: "Candle data too old",
    no_eligible_strategy: "No eligible paper strategy",
    no_edge_after_cost: "No edge after cost",
    negative_edge_after_cost: "Negative edge after cost",
    allocator_block: "Allocator or validator block",
    duplicate_buy: "Duplicate buy blocked",
    stock_market_closed: "Stock market closed",
  };
  return known[normalized] ?? normalized.replace(/_/g, " ");
}

function numeric(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function priceLabel(value: unknown): string {
  const n = numeric(value);
  if (!n) return "-";
  return n >= 1 ? n.toFixed(4) : n.toFixed(8);
}

export function PushPullTraderPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [lessons, setLessons] = useState<Record<string, unknown>[]>([]);
  const [signals, setSignals] = useState<Record<string, unknown> | null>(null);
  const [latestTick, setLatestTick] = useState<Record<string, unknown> | null>(null);
  const [orderProof, setOrderProof] = useState<Record<string, unknown> | null>(null);
  const [diagnosis, setDiagnosis] = useState<Record<string, unknown> | null>(null);
  const [signalSymbol, setSignalSymbol] = useState("BTC/USD");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [cockpit, liveStatus, sig] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/cockpit", { timeoutMs: 90000 }),
      apiGet<Record<string, unknown>>("/api/push-pull/status"),
      apiGet<Record<string, unknown>>(`/api/push-pull/signals?symbol=${encodeURIComponent(signalSymbol)}`),
    ]);

    if (cockpit.ok && cockpit.data) {
      const d = cockpit.data;
      const ctrl = (d.control as Record<string, unknown>) || {};
      const reasons = (ctrl.blockers as unknown[]) ?? [];
      const primaryReason =
        String(d.why_zero_shortlist ?? "") ||
        reasons.map(String).filter(Boolean).join(", ") ||
        String(d.ai_cockpit_message ?? "");
      setLatestTick(null);
      setOrderProof({ recent_trades: d.recent_trades });
      setLessons([]);
      setDiagnosis({
        why_no_order: primaryReason,
        no_trade_reasons: reasons,
        next_action: ctrl.can_place_paper_orders ? "Run agent cycle" : "Fix blockers or rebuild",
        experiments: [],
      });
    }
    if (liveStatus.ok && liveStatus.data) {
      setStatus(liveStatus.data);
    }
    if (sig.ok && sig.data) {
      setSignals(sig.data);
    }
    setLoading(false);
  }, [signalSymbol]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const reasonBreakdown = useMemo(() => {
    const rb = (latestTick?.reason_breakdown as Record<string, number>) ?? {};
    return Object.entries(rb)
      .filter(([, value]) => Number(value) > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 6);
  }, [latestTick]);

  if (loading) return <EmptyState message="Loading Push-Pull Trader..." />;

  const labels = (signals?.push_pull_labels as Record<string, unknown>) ?? {};
  const msgs = (status?.operator_messages as string[]) ?? [];
  const topCandidate = latestTick?.top_candidate as Record<string, unknown> | undefined;

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <TrendingUp className="h-6 w-6 text-hive-cyan" />
        Push-Pull Trader
      </h1>
      <p className="text-sm text-slate-400">
        Scan | score push | check pull risk | pass cage | submit paper order | watch exit
      </p>

      <div className="grid gap-3 md:grid-cols-4">
        {[
          ["Scanned", latestTick?.symbols_scanned_count],
          ["Fresh Bars", latestTick?.fresh_bar_count],
          ["Push Signals", latestTick?.push_signals_found],
          ["Orders", latestTick?.order_count ?? latestTick?.orders_created],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">{String(label)}</p>
            <p className="text-lg font-semibold text-white">{numeric(value)}</p>
          </div>
        ))}
      </div>

      <PushPullCandleCard tick={latestTick} />
      <PaperOrderProofPanel proof={orderProof} />

      <GlassPanel title="Why no paper order?">
        {diagnosis?.why_no_order ? (
          <p className="text-xs text-slate-300">{humanize(String(diagnosis.why_no_order))}</p>
        ) : (
          <p className="text-xs text-slate-500">No blocker recorded yet. Wait for the next scheduler tick.</p>
        )}
        {reasonBreakdown.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {reasonBreakdown.map(([key, value]) => (
              <span key={key} className="rounded border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-[11px] text-amber-200">
                {humanize(key)}: {Number(value)}
              </span>
            ))}
          </div>
        ) : null}
        {diagnosis?.next_action ? (
          <p className="text-[11px] text-hive-cyan mt-2">{String(diagnosis.next_action)}</p>
        ) : null}
      </GlassPanel>

      <GlassPanel title="Market mode">
        <p className="text-white text-sm">{String(status?.market_mode_label ?? status?.market_mode ?? "Unknown")}</p>
        <div className="flex flex-wrap gap-2 mt-2">
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Stocks: {status?.stock_push_pull_active ? "Active" : "Off"}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Crypto: {status?.crypto_push_pull_active ? "Active" : "Off"}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300">
            Paper only
          </span>
        </div>
        {msgs.map((m) => (
          <p key={m} className="text-[11px] text-slate-500 mt-1">
            {m}
          </p>
        ))}
      </GlassPanel>

      <GlassPanel title="Push-Pull signal">
        <div className="flex gap-2 mb-2">
          <input
            className="rounded bg-black/40 border border-white/10 px-2 py-1 text-xs text-white w-32"
            value={signalSymbol}
            onChange={(e) => setSignalSymbol(e.target.value)}
            placeholder="BTC/USD"
          />
          <button
            type="button"
            className="text-[10px] px-2 py-1 rounded bg-hive-cyan/20 text-hive-cyan"
            onClick={() => void load()}
          >
            Refresh
          </button>
        </div>
        {Object.keys(labels).length > 0 ? (
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            {Object.entries(labels).map(([k, v]) => (
              <div key={k}>
                <span className="text-slate-500">{humanize(k)}: </span>
                <span className="text-white">{String(v ?? "-")}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No signal data yet.</p>
        )}
      </GlassPanel>

      <GlassPanel title="Top candidate">
        {topCandidate ? (
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <span className="text-slate-500">Symbol: </span>
              <span className="text-white">{String(topCandidate.symbol ?? "-")}</span>
            </div>
            <div>
              <span className="text-slate-500">Quality: </span>
              <span className="text-white">{numeric(topCandidate.trade_quality_score).toFixed(2)}</span>
            </div>
            <div>
              <span className="text-slate-500">Push score: </span>
              <span className="text-white">{numeric(topCandidate.push_score).toFixed(2)}</span>
            </div>
            <div>
              <span className="text-slate-500">Edge after cost: </span>
              <span className="text-white">{numeric(topCandidate.edge_after_cost_bps).toFixed(1)} bps</span>
            </div>
            <div>
              <span className="text-slate-500">Risk reward: </span>
              <span className="text-white">{numeric(topCandidate.risk_reward).toFixed(2)}R</span>
            </div>
            <div className="col-span-2">
              <span className="text-slate-500">Decision: </span>
              <span className="text-white">{humanize(String(topCandidate.no_trade_reason ?? "waiting"))}</span>
            </div>
            {(() => {
              const levels = (topCandidate.dynamic_exit_levels as Record<string, unknown>) ?? {};
              if (!levels.stop_loss && !levels.take_profit) return null;
              return (
                <div className="col-span-2 mt-2 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.04] p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-[10px] uppercase tracking-wide text-cyan-200">Dynamic exit bars</span>
                    <span className="text-[10px] text-slate-400">
                      {String(levels.volatility_regime ?? "unknown")} volatility
                    </span>
                  </div>
                  <div className="grid gap-1.5 sm:grid-cols-2">
                    {[
                      ["Entry", levels.entry_price, "text-white"],
                      ["Stop", levels.stop_loss, "text-rose-300"],
                      ["Target", levels.take_profit, "text-emerald-300"],
                      ["Trail", levels.trailing_stop, "text-amber-200"],
                      ["Invalidation", levels.invalidation_price, "text-orange-200"],
                    ].map(([label, value, tone]) => (
                      <div key={String(label)} className="flex items-center justify-between rounded border border-white/5 bg-black/20 px-2 py-1">
                        <span className="text-slate-500">{String(label)}</span>
                        <span className={`${tone} font-mono`}>{priceLabel(value)}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-[10px] text-slate-400">
                    Stop, target, trail, and invalidation move from ATR, spread, push quality, edge, and sentiment context.
                  </p>
                </div>
              );
            })()}
            {(() => {
              const components = (topCandidate.score_components as Record<string, unknown>) ?? {};
              return (
                <>
                  <div>
                    <span className="text-slate-500">Adaptive entry: </span>
                    <span className="text-white">{(numeric(components.adaptive_enter_threshold) * 100).toFixed(0)}%</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Paper exploration: </span>
                    <span className="text-white">{components.paper_exploration ? "On" : "Off"}</span>
                  </div>
                </>
              );
            })()}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No scored candidate from the latest tick.</p>
        )}
      </GlassPanel>

      <GlassPanel title="Latest lessons">
        {lessons.length === 0 ? (
          <p className="text-sm text-slate-500">No useful lesson saved yet.</p>
        ) : (
          <ul className="space-y-2">
            {lessons.map((l) => (
              <li key={String(l.id)} className="text-[11px] text-slate-400">
                <span className="text-white">{String(l.title)}</span>
                <p>{String(l.lesson_plain ?? l.summary)}</p>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </section>
  );
}
