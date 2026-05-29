"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Brain,
  CircleDollarSign,
  LogOut,
  RefreshCw,
  Send,
  ShieldCheck,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type ConsolePayload = {
  status?: string;
  generated_at_utc?: string;
  paper_broker?: boolean;
  live_trading_locked?: boolean;
  message?: string;
  account?: {
    alpaca_configured?: boolean;
    alpaca_connected?: boolean;
    cash?: number | null;
    equity?: number | null;
    buying_power?: number | null;
    daily_pl?: number | null;
    daily_pl_pct?: number | null;
    rate_limited?: boolean;
    message?: string;
  };
  autopilot?: {
    paper_learning?: boolean;
    scheduler_enabled?: boolean;
    can_place_paper_orders_now?: boolean;
    paper_orders_enabled?: boolean;
    blockers?: string[];
  };
  positions?: PositionRow[];
  open_positions_count?: number;
  shortlist?: ShortlistRow[];
  shortlist_count?: number;
  scored_symbols?: number;
  no_trade_reason_breakdown?: Record<string, number>;
  latest_decision?: {
    symbol?: string;
    side?: string;
    decision?: string;
    reason_code?: string | null;
    reason_text?: string | null;
    execution_status?: string | null;
    approved_notional?: number | null;
  } | null;
  latest_ai_nudge?: {
    decision?: string;
    confidence?: number;
    summary?: string;
  } | null;
};

type PositionRow = {
  symbol?: string;
  qty?: number;
  current_price?: number;
  avg_entry_price?: number;
  unrealized_pl?: number;
  unrealized_pl_pct?: number;
  action?: string;
  reason?: string;
  dynamic_exit_levels?: {
    stop_loss?: number;
    take_profit?: number;
    trailing_stop?: number;
    invalidation_price?: number;
    risk_reward?: number;
  } | null;
};

type ShortlistRow = {
  symbol?: string;
  asset_class?: string;
  push_score?: number;
  trade_quality_score?: number;
  edge_after_cost_bps?: number;
  pattern_name?: string;
  stop_loss?: number;
  take_profit?: number;
  trailing_stop?: number;
  no_trade_reason?: string;
};

function n(value: unknown): number | null {
  const out = Number(value);
  return Number.isFinite(out) ? out : null;
}

function money(value: unknown, digits = 2): string {
  const out = n(value);
  return out === null ? "--" : `$${out.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
}

function pct(value: unknown): string {
  const out = n(value);
  return out === null ? "--" : `${out.toFixed(2)}%`;
}

function score(value: unknown): string {
  const out = n(value);
  return out === null ? "--" : `${Math.round(out * 100)}`;
}

function label(text: unknown): string {
  return String(text ?? "--").replace(/_/g, " ");
}

function statusTone(ok?: boolean): string {
  return ok ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-200" : "border-amber-300/25 bg-amber-300/10 text-amber-200";
}

export function TraderConsolePanel() {
  const [data, setData] = useState<ConsolePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [symbol, setSymbol] = useState("BTC/USD");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiGet<Record<string, unknown>>("/api/cockpit", { timeoutMs: 5000 });
    if (res.ok && res.data) {
      const c = res.data;
      const ctrl = (c.control as Record<string, unknown>) || {};
      const acct = (c.account as Record<string, unknown>) || {};
      const mapped: ConsolePayload = {
        status: "ok",
        generated_at_utc: c.generated_at_utc as string,
        paper_broker: true,
        live_trading_locked: true,
        message: c.ai_cockpit_message as string,
        account: {
          alpaca_configured: Boolean(acct.connected),
          alpaca_connected: Boolean(acct.connected),
          equity: acct.equity as number,
          daily_pl: acct.daily_pl as number,
        },
        autopilot: {
          paper_learning: Boolean(ctrl.paper_learning_on),
          can_place_paper_orders_now: Boolean(ctrl.can_place_paper_orders),
          blockers: (ctrl.blockers as string[]) || [],
        },
        positions: (c.positions as PositionRow[]) || [],
        shortlist: (c.shortlist as ShortlistRow[]) || [],
        shortlist_count: ((c.funnel as Record<string, number>)?.shortlist as number) || 0,
        no_trade_reason_breakdown: (c.block_breakdown as Record<string, number>) || {},
      };
      setData(mapped);
      setMessage(null);
      setLoading(false);
      return;
    }
    setMessage(res.error || "Trader Console is temporarily unavailable.");
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  const blockers = useMemo(() => {
    const rows = Object.entries(data?.no_trade_reason_breakdown ?? {})
      .filter(([, value]) => Number(value) > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 5);
    return rows;
  }, [data]);

  const submitBuy = async (event: FormEvent) => {
    event.preventDefault();
    if (!symbol.trim()) return;
    if (!window.confirm(`Send a caged paper buy request for ${symbol.trim().toUpperCase()}?`)) return;
    setBusy("buy");
    const res = await apiPostOperator<Record<string, unknown>>("/api/paper/manual-buy", {
      symbol: symbol.trim().toUpperCase(),
      actor: "operator",
    });
    setMessage(res.ok ? `Paper buy request: ${label((res.data as { status?: string })?.status)}` : res.error);
    setBusy(null);
    await load();
  };

  const submitSell = async (row: PositionRow) => {
    const sym = String(row.symbol || "");
    if (!sym) return;
    if (!window.confirm(`Send a caged paper sell request for ${sym}?`)) return;
    setBusy(`sell:${sym}`);
    const res = await apiPostOperator<Record<string, unknown>>(
      `/api/positions/${encodeURIComponent(sym)}/manual-exit-request`,
      { actor: "operator" }
    );
    setMessage(res.ok ? `Paper sell request: ${label((res.data as { status?: string })?.status)}` : res.error);
    setBusy(null);
    await load();
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="label-caps text-hive-cyan">Trader Console</p>
          <h1 className="mt-1 text-3xl font-semibold text-white">Caged Hive Quant</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">
            Paper-only formula trading with dynamic stop, target, trailing stop, and candle-cycle review.
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-md border border-cyan-300/25 bg-cyan-300/10 px-3 py-2 text-sm font-semibold text-cyan-100 hover:bg-cyan-300/15"
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {message && (
        <div className="rounded-md border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">
          {message}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <GlassPanel title="Alpaca Paper">
          <div className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${statusTone(data?.account?.alpaca_connected)}`}>
            {data?.account?.alpaca_connected ? "Connected" : "Not connected"}
          </div>
          <p className="mt-3 text-2xl font-semibold text-white">{money(data?.account?.equity)}</p>
          <p className="mt-1 text-xs text-slate-500">Equity with cash {money(data?.account?.cash)}</p>
        </GlassPanel>

        <GlassPanel title="Paper Lock" icon={<ShieldCheck className="h-4 w-4" />}>
          <div className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${statusTone(data?.paper_broker && data?.live_trading_locked)}`}>
            {data?.paper_broker && data?.live_trading_locked ? "Paper only" : "Blocked"}
          </div>
          <p className="mt-3 text-sm text-slate-300">Live trading locked. Manual actions still use the cage.</p>
        </GlassPanel>

        <GlassPanel title="Autopilot" icon={<Zap className="h-4 w-4" />}>
          <p className="text-2xl font-semibold text-white">
            {data?.autopilot?.can_place_paper_orders_now ? "Ready" : "Watching"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Paper learning {data?.autopilot?.paper_learning ? "on" : "off"} · Scheduler {data?.autopilot?.scheduler_enabled ? "on" : "off"}
          </p>
        </GlassPanel>

        <GlassPanel title="Buying Power" icon={<CircleDollarSign className="h-4 w-4" />}>
          <p className="text-2xl font-semibold text-white">{money(data?.account?.buying_power)}</p>
          <p className="mt-1 text-xs text-slate-500">Daily P/L {money(data?.account?.daily_pl)} · {pct(data?.account?.daily_pl_pct)}</p>
        </GlassPanel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <GlassPanel title="Open Positions" icon={<Target className="h-4 w-4" />}>
          {(data?.positions ?? []).length === 0 ? (
            <p className="text-sm text-slate-500">No broker-confirmed open positions.</p>
          ) : (
            <div className="space-y-3">
              {(data?.positions ?? []).map((p) => {
                const levels = p.dynamic_exit_levels ?? {};
                const sym = String(p.symbol || "");
                return (
                  <div key={sym} className="rounded-md border border-white/[0.06] bg-white/[0.025] p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="min-w-0">
                          <TickerSymbol symbol={sym} size="sm" labelClassName="text-sm font-semibold text-white" />
                          <p className="text-xs text-slate-500 mt-1">
                            Qty {n(p.qty)?.toPrecision(6) ?? "--"} · Avg {money(p.avg_entry_price, 4)} · Now {money(p.current_price, 4)}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => submitSell(p)}
                        disabled={busy === `sell:${sym}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-rose-300/30 bg-rose-300/10 px-2.5 py-1.5 text-xs font-semibold text-rose-100 hover:bg-rose-300/15 disabled:opacity-50"
                      >
                        <LogOut className="h-3.5 w-3.5" />
                        Sell Paper
                      </button>
                    </div>
                    <div className="mt-3 grid gap-2 sm:grid-cols-4">
                      <Metric labelText="Stop" value={money(levels.stop_loss, 4)} />
                      <Metric labelText="Target" value={money(levels.take_profit, 4)} />
                      <Metric labelText="Trail" value={money(levels.trailing_stop, 4)} />
                      <Metric labelText="P/L" value={`${money(p.unrealized_pl)} · ${pct(p.unrealized_pl_pct)}`} />
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      Candle review: {label(p.action)} · {label(p.reason)}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </GlassPanel>

        <GlassPanel title="Manual Paper Action" icon={<Send className="h-4 w-4" />}>
          <form onSubmit={submitBuy} className="flex gap-2">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              placeholder="BTC/USD"
            />
            <button
              type="submit"
              disabled={busy === "buy"}
              className="inline-flex items-center gap-2 rounded-md border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/15 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
              Buy Paper
            </button>
          </form>
          <p className="mt-3 text-xs text-slate-500">
            Buy requests must pass paper broker, live lock, data freshness, positive edge, dynamic exits, duplicate checks, and preflight.
          </p>
          <div className="mt-4 rounded-md border border-white/[0.06] bg-black/20 p-3">
            <p className="label-caps text-slate-400">Latest Decision</p>
            <p className="mt-1 text-sm font-semibold text-white">
              {data?.latest_decision ? `${data.latest_decision.symbol} ${label(data.latest_decision.decision)}` : "No paper decision yet"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {data?.latest_decision?.reason_text || data?.latest_decision?.reason_code || data?.message || "Waiting for the next candle cycle."}
            </p>
          </div>
        </GlassPanel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
        <GlassPanel title="Paper Shortlist" icon={<TrendingUp className="h-4 w-4" />}>
          {(data?.shortlist ?? []).length === 0 ? (
            <div className="rounded-md border border-amber-300/15 bg-amber-300/10 p-3">
              <p className="text-sm text-amber-100">{data?.message || "No candidate passed hard paper gates yet."}</p>
              {blockers.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {blockers.map(([key, value]) => (
                    <span key={key} className="rounded border border-amber-300/20 px-2 py-0.5 text-xs text-amber-100">
                      {label(key)}: {value}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {(data?.shortlist ?? []).map((s) => (
                <div key={s.symbol} className="flex items-center gap-3 rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <TickerSymbol symbol={String(s.symbol || "")} assetClass={s.asset_class} size="sm" labelClassName="text-sm font-semibold text-white" />
                    <p className="text-xs text-slate-500 mt-1">
                      {label(s.pattern_name || "push pull")} · Edge {n(s.edge_after_cost_bps)?.toFixed(1) ?? "--"} bps
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-semibold text-cyan-100">{score(s.trade_quality_score)}</p>
                    <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Quality</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassPanel>

        <GlassPanel title="AI Nudge" icon={<Brain className="h-4 w-4" />}>
          <div className="rounded-md border border-white/[0.06] bg-white/[0.025] p-3">
            <p className="text-sm font-semibold text-white">
              {data?.latest_ai_nudge?.decision ? label(data.latest_ai_nudge.decision) : "No current Gemini review"}
            </p>
            <p className="mt-2 text-sm text-slate-400">
              {data?.latest_ai_nudge?.summary || "Gemini remains advisory only. It can propose parameter changes, but it cannot submit orders or unlock live trading."}
            </p>
            {data?.latest_ai_nudge?.confidence !== undefined && (
              <p className="mt-3 text-xs text-slate-500">Confidence {score(data.latest_ai_nudge.confidence)}</p>
            )}
          </div>
          <details className="mt-4">
            <summary className="cursor-pointer text-xs font-semibold text-slate-400 hover:text-slate-200">
              Show technical details
            </summary>
            <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-black/40 p-3 text-[10px] text-slate-400">
              {JSON.stringify(data, null, 2)}
            </pre>
          </details>
        </GlassPanel>
      </div>
    </div>
  );
}

function Metric({ labelText, value }: { labelText: string; value: string }) {
  return (
    <div className="rounded-md border border-white/[0.05] bg-black/20 px-2.5 py-2">
      <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{labelText}</p>
      <p className="mt-1 text-sm font-semibold text-slate-100">{value}</p>
    </div>
  );
}
