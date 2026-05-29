"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, FlaskConical, RefreshCw, Shield } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { CockpitFunnelBrain } from "@/components/cockpit/CockpitFunnelBrain";
import { apiGet } from "@/lib/apiClient";
import { dispatchCockpitRefresh } from "@/lib/cockpitEvents";

type Cockpit = {
  generated_at_utc?: string;
  live_truth?: boolean;
  ai_cockpit_message?: string;
  watchlist?: {
    total?: number;
    crypto?: { usd_pairs?: number; symbols?: string[] };
    stocks?: { count?: number; symbols?: string[] };
  };
  funnel?: Record<string, number>;
  shortlist?: Array<{ symbol: string; universe_rank_score?: number; trade_quality_score?: number; stop_loss?: number; take_profit?: number }>;
  eligible_trades?: Array<{ symbol: string; universe_rank_score?: number; trade_quality_score?: number; stop_loss?: number; take_profit?: number }>;
  why_zero_shortlist?: string;
  scores?: Array<{
    symbol: string;
    pass?: boolean;
    entry_allowed?: boolean;
    quality_score?: number;
    trade_quality_score?: number;
    push_score?: number;
  }>;
  passed_count?: number;
  control?: {
    can_place_paper_orders?: boolean;
    paper_learning_on?: boolean;
    bot_can_place?: boolean;
    blockers?: string[];
    mode?: string;
  };
  account?: { connected?: boolean; equity?: number; daily_pl?: number };
  alpaca_connected?: boolean;
  positions?: Array<{ symbol: string; qty: number; unrealized_pl?: number }>;
  recent_trades?: Array<{ symbol: string; side: string; status: string }>;
  weights?: { universe_ranking?: Record<string, number>; min_rank_score?: number };
  ai_brain?: { active_lessons?: number; recent_lessons?: Array<{ title: string; memory_type?: string; symbol?: string }> };
  research_os?: {
    research_jobs_running?: number;
    latest_backtest?: { run_id?: string; status?: string; metrics?: Record<string, unknown> } | null;
    latest_strategy_proposal?: Record<string, unknown> | null;
    latest_risk_audit?: { status?: string; pass_fail?: string; risk_score?: number } | null;
    latest_promotion_proposal?: Record<string, unknown> | null;
    paper_exploration_status?: string;
    live_readiness_status?: { live_locked?: boolean; tiny_live_architecture_present?: boolean } | null;
    code_proposal_pending_count?: number;
    tradingview_status?: { mode?: string; execution_allowed?: boolean } | null;
    agent_loop_status?: { latest_status?: string | null; orders_submitted?: number; live_flags_changed?: boolean } | null;
    next_research_action?: string;
  };
};

export function CockpitDashboard() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    const r = await apiGet<Cockpit>("/api/mission-control/status", { timeoutMs: 5000 });
    if (r.ok && r.data) {
      setData(r.data);
      dispatchCockpitRefresh(r.data as Record<string, unknown>);
      setLoading(false);
    } else {
      setErr(r.error || "Cockpit unavailable - check API_URL on Railway frontend");
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 25000);
    return () => clearInterval(t);
  }, [load]);

  const f = data?.funnel ?? {};
  const ctrl = data?.control ?? {};
  const eligible =
    data?.eligible_trades ??
    data?.shortlist ??
    (data?.scores ?? []).filter((s) => s.entry_allowed);

  return (
    <div className="space-y-4 max-w-6xl">
      <header>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Brain className="h-7 w-7 text-hive-cyan" />
          AI Trading Cockpit
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Cached product truth - paper-only execution, dynamic SL/TP, and operator-triggered heavy refreshes.
        </p>
        {data?.ai_cockpit_message && (
          <p className="text-xs text-hive-cyan/90 mt-2 border border-hive-cyan/20 rounded-lg px-3 py-2 bg-hive-cyan/5">
            {data.ai_cockpit_message}
          </p>
        )}
        {err && (
          <p className="text-xs text-amber-400 mt-2">
            {err}
            <span className="block text-slate-500 mt-1">
              Top banner and cards use /api/mission-control/status. If this fails, verify the backend deployment and
              database migrations.
            </span>
          </p>
        )}
      </header>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-white/10 text-slate-300 hover:bg-white/5"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh live
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        {[
          ["Paper learning", ctrl.paper_learning_on ? "ON" : "OFF", ctrl.paper_learning_on ? "#00FF66" : "#F59E0B"],
          ["Bot can trade", ctrl.bot_can_place ? "YES" : "NO", ctrl.bot_can_place ? "#00FF66" : "#F59E0B"],
          ["Equity", data?.account?.equity != null ? `$${data.account.equity.toFixed(2)}` : "-", "#fff"],
          [
            "Crypto pairs",
            String(data?.watchlist?.crypto?.usd_pairs ?? data?.watchlist?.crypto?.symbols?.length ?? 0),
            "#00dbe9",
          ],
          [
            "Stocks",
            String(data?.watchlist?.stocks?.count ?? data?.watchlist?.stocks?.symbols?.length ?? 0),
            "#00dbe9",
          ],
          [
            "Alpaca",
            data?.account?.connected || data?.alpaca_connected ? "CONNECTED" : "OFFLINE",
            data?.account?.connected || data?.alpaca_connected ? "#00FF66" : "#EF4444",
          ],
        ].map(([label, val, color]) => (
          <div key={label} className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase text-slate-500">{label}</p>
            <p className="text-lg font-bold mono-metric" style={{ color }}>
              {val}
            </p>
          </div>
        ))}
      </div>

      <CockpitFunnelBrain funnel={f} blockers={data?.why_zero_shortlist} aiNote={data?.ai_cockpit_message} />

      {data?.research_os && (
        <GlassPanel title="Research OS" icon={<FlaskConical className="h-4 w-4" />}>
          <div className="grid gap-3 md:grid-cols-4 text-xs">
            <div>
              <p className="text-slate-500 uppercase text-[10px]">Research jobs</p>
              <p className="text-white font-semibold">{data.research_os.research_jobs_running ?? 0}</p>
            </div>
            <div>
              <p className="text-slate-500 uppercase text-[10px]">Latest backtest</p>
              <p className="text-white font-semibold">{data.research_os.latest_backtest?.status ?? "none"}</p>
            </div>
            <div>
              <p className="text-slate-500 uppercase text-[10px]">Code drafts</p>
              <p className="text-white font-semibold">{data.research_os.code_proposal_pending_count ?? 0}</p>
            </div>
            <div>
              <p className="text-slate-500 uppercase text-[10px]">Live readiness</p>
              <p className="text-emerald-300 font-semibold">
                {data.research_os.live_readiness_status?.live_locked === false ? "review" : "locked"}
              </p>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-slate-400">
            {data.research_os.next_research_action ?? "No research action queued."}
          </p>
        </GlassPanel>
      )}

      {data?.ai_brain && (data.ai_brain.active_lessons ?? 0) > 0 && (
        <p className="text-[10px] text-violet-200/80">
          AI memory: {data.ai_brain.active_lessons} active lesson(s)
          {data.ai_brain.recent_lessons?.[0]?.title
            ? ` · latest: ${data.ai_brain.recent_lessons[0].title}`
            : ""}
        </p>
      )}

      <GlassPanel title="TradingView wrapper">
        <p className="text-[11px] text-slate-400">
          Chart overlays are display-only and live on the TradingView page. The cockpit stays on cached truth so opening
          Mission Control does not fetch fresh bars or rescore the universe.
        </p>
        <a
          href="/tradingview"
          className="mt-3 inline-flex rounded-lg border border-hive-cyan/30 px-3 py-2 text-xs text-hive-cyan hover:bg-hive-cyan/10"
        >
          Open TradingView overlays
        </a>
      </GlassPanel>

      <GlassPanel title="Eligible trades (all pass gates — no shortlist cap)" icon={<Shield className="h-4 w-4" />}>
        {eligible.length === 0 ? (
          <p className="text-[11px] text-slate-500">
            None this scan — radar still watches full universe; next cycle retries all eligible symbols with TP/SL bands.
          </p>
        ) : (
          <ul className="space-y-1 max-h-[280px] overflow-y-auto">
            {eligible.map((s) => {
              const row = s as {
                symbol: string;
                universe_rank_score?: number;
                trade_quality_score?: number;
                quality_score?: number;
                stop_loss?: number;
                take_profit?: number;
              };
              const q =
                row.universe_rank_score != null
                  ? (row.universe_rank_score * 100).toFixed(0)
                  : ((row.trade_quality_score ?? row.quality_score ?? 0) * 100).toFixed(0);
              return (
              <li key={row.symbol} className="text-[11px] flex justify-between gap-2 text-white border-b border-white/5 py-1">
                <TickerSymbol symbol={row.symbol} size="sm" labelClassName="text-[11px] text-white" />
                <span className="text-hive-cyan shrink-0">
                  Q{q}
                  {row.stop_loss != null ? ` · SL ${Number(row.stop_loss).toFixed(2)}` : ""}
                  {row.take_profit != null ? ` · TP ${Number(row.take_profit).toFixed(2)}` : ""}
                </span>
              </li>
              );
            })}
          </ul>
        )}
      </GlassPanel>

      <GlassPanel title="Recent paper trades">
        {(data?.recent_trades?.length ?? 0) === 0 ? (
          <p className="text-[11px] text-slate-500">No trades yet - waiting for the next approved paper cycle.</p>
        ) : (
          <ul className="space-y-1">
            {data?.recent_trades?.map((t, i) => (
              <li key={i} className="text-[10px] text-slate-300 flex items-center gap-2">
                <TickerSymbol symbol={t.symbol} size="sm" labelClassName="text-[10px] text-slate-300" />
                <span>
                  {t.side} - {t.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <p className="text-[9px] text-slate-600">
        Live @ {data?.generated_at_utc?.slice(0, 19) ?? "-"} - scheduler ~45s when paper learning ON
      </p>
    </div>
  );
}
