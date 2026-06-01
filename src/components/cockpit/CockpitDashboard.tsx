"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, FlaskConical, RefreshCw, Shield } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { CockpitFunnelBrain } from "@/components/cockpit/CockpitFunnelBrain";
import { CockpitAutopilotChip } from "@/components/cockpit/CockpitAutopilotChip";
import { CockpitPortfolioHistory } from "@/components/cockpit/CockpitPortfolioHistory";
import { apiGet, apiPostOperator } from "@/lib/apiClient";
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
  alpha_factory?: {
    can_trade_paper_now?: boolean;
    reason?: string;
    paper_candidate_count?: number;
    rejected_strategy_count?: number;
    best_candidate?: { symbol?: string; strategy_family?: string; edge_after_cost_bps?: number } | null;
    autonomous_status?: { plain_english?: string; enabled?: boolean } | null;
    plain_english?: string;
  };
  paper_execution?: {
    paper_broker_connected?: boolean;
    paper_broker?: boolean;
    paper_orders_enabled?: boolean;
    paper_learning_on?: boolean;
    scheduler_enabled?: boolean;
    kill_switch_active?: boolean;
    drawdown_blocker?: { message?: string; switch_name?: string } | null;
    open_positions_count?: number;
    active_orders_count?: number;
    can_place_paper_orders_now?: boolean;
    bot_can_submit_paper_entries_now?: boolean;
    broker_connected?: boolean;
    paper_mode_active?: boolean;
    new_entries_allowed?: boolean;
    exits_allowed?: boolean;
    kill_switch_blocks_exits?: boolean;
    entries_exits_summary?: string;
    live_trading_locked?: boolean;
    blockers?: string[];
    next_action?: string;
    kill_switch?: { account_daily_pl_pct?: number | null; account_drawdown_pct?: number | null; state?: string };
  };
};

function symbolKey(symbol: string): string {
  return String(symbol || "").toUpperCase().replace(/[/-]/g, "");
}

function dedupeEligible<T extends { symbol: string; trade_quality_score?: number; universe_rank_score?: number; quality_score?: number }>(rows: T[]): T[] {
  const best = new Map<string, T>();
  for (const row of rows.filter((r) => r.symbol)) {
    const key = symbolKey(row.symbol);
    const prev = best.get(key);
    const prevScore = Number(prev?.universe_rank_score ?? prev?.trade_quality_score ?? prev?.quality_score ?? 0);
    const nextScore = Number(row.universe_rank_score ?? row.trade_quality_score ?? row.quality_score ?? 0);
    if (!prev || nextScore >= prevScore) best.set(key, row);
  }
  return Array.from(best.values());
}

export function CockpitDashboard() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [readinessMsg, setReadinessMsg] = useState<string | null>(null);
  const [checkingReadiness, setCheckingReadiness] = useState(false);

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
  const paper = data?.paper_execution ?? {};
  const eligible = dedupeEligible(
    data?.eligible_trades ??
    data?.shortlist ??
    (data?.scores ?? []).filter((s) => s.entry_allowed)
  );
  const canSubmitEntries = Boolean(paper.new_entries_allowed ?? paper.bot_can_submit_paper_entries_now ?? paper.can_place_paper_orders_now ?? ctrl.bot_can_place);
  // Exits are never blocked by the kill switch — the bot can always manage/close open positions while the paper broker is connected.
  const exitsAllowed = Boolean(paper.exits_allowed ?? (paper.broker_connected ?? paper.paper_broker_connected ?? paper.paper_broker));
  const entriesExitsSummary = paper.entries_exits_summary ?? (
    canSubmitEntries
      ? "Paper entries and exits are both available (paper-only; live trading locked)."
      : exitsAllowed
        ? "New paper entries are paused; the bot can still manage and exit open positions."
        : "Paper broker not connected: neither entries nor exits can submit."
  );
  const drawdownReason = paper.drawdown_blocker?.message;
  const alpha = data?.alpha_factory ?? {};

  async function checkPaperReadiness() {
    setCheckingReadiness(true);
    setReadinessMsg(null);
    const res = await apiPostOperator<{ paper_entry_allowed?: boolean; next_action?: string; readiness?: { blockers?: string[] } }>(
      "/api/execution/paper/readiness-check",
      { actor: "cockpit_ui" },
      { timeoutMs: 10000 }
    );
    if (res.ok) {
      const allowed = Boolean(res.data?.paper_entry_allowed);
      const blockers = res.data?.readiness?.blockers ?? [];
      setReadinessMsg(
        allowed
          ? "Paper entries are allowed when a candidate passes the cage."
          : String(res.data?.next_action ?? blockers[0] ?? "Paper entries are currently blocked.")
      );
    } else {
      setReadinessMsg(res.error || "Readiness check failed.");
    }
    setCheckingReadiness(false);
    await load();
  }

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

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded border border-white/10 text-slate-300 hover:bg-white/5"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh live
        </button>
        <CockpitAutopilotChip />
      </div>

      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        {[
          ["Paper learning", ctrl.paper_learning_on ? "ON" : "OFF", ctrl.paper_learning_on ? "#00FF66" : "#F59E0B"],
          ["New paper entries", canSubmitEntries ? "ON" : "PAUSED", canSubmitEntries ? "#00FF66" : "#F59E0B"],
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

      <CockpitPortfolioHistory />

      <CockpitFunnelBrain funnel={f} blockers={data?.why_zero_shortlist} aiNote={data?.ai_cockpit_message} />

      <GlassPanel title="Paper Trading Readiness" icon={<Shield className="h-4 w-4" />}>
        <div className="grid gap-2 text-xs md:grid-cols-3 lg:grid-cols-5">
          {[
            ["Paper broker connected", paper.paper_broker_connected ?? paper.paper_broker ? "Yes" : "No", paper.paper_broker_connected ?? paper.paper_broker],
            ["Paper orders enabled", paper.paper_orders_enabled ? "Yes" : "No", paper.paper_orders_enabled],
            ["Paper learning enabled", paper.paper_learning_on ? "Yes" : "No", paper.paper_learning_on],
            ["Scheduler enabled", paper.scheduler_enabled ? "Yes" : "No", paper.scheduler_enabled],
            ["Kill switch active", paper.kill_switch_active ? "Yes" : "No", !paper.kill_switch_active],
            ["Open positions", String(paper.open_positions_count ?? data?.positions?.length ?? 0), true],
            ["Active orders", String(paper.active_orders_count ?? 0), true],
            ["New entries allowed", canSubmitEntries ? "Yes" : "No", canSubmitEntries],
            ["Exits allowed", exitsAllowed ? "Yes" : "No", exitsAllowed],
          ].map(([label, value, ok]) => (
            <div key={String(label)} className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
              <p className="text-[10px] uppercase text-slate-500">{label}</p>
              <p className={`mt-1 font-semibold ${ok ? "text-emerald-300" : "text-amber-300"}`}>{String(value)}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 p-3 text-[11px] text-amber-100">
          <p className="font-semibold text-amber-50">{entriesExitsSummary}</p>
          {drawdownReason ? (
            <p className="mt-1">New paper entries are paused by the daily drawdown kill switch (exits still allowed). Wait for window reset or intentionally change risk config. Detail: {drawdownReason}</p>
          ) : canSubmitEntries ? (
            <p className="mt-1">Paper entries can submit only when a candidate passes the deterministic execution cage.</p>
          ) : (
            <p className="mt-1">{paper.next_action ?? paper.blockers?.[0] ?? "New paper entries are currently paused; check operator controls and latest scan freshness."}</p>
          )}
        </div>
        <button
          type="button"
          onClick={checkPaperReadiness}
          disabled={checkingReadiness}
          className="mt-3 rounded-lg border border-hive-cyan/30 px-3 py-2 text-xs text-hive-cyan hover:bg-hive-cyan/10 disabled:opacity-50"
        >
          {checkingReadiness ? "Checking..." : "Check paper-entry readiness"}
        </button>
        {readinessMsg && <p className="mt-2 text-[11px] text-slate-400">{readinessMsg}</p>}
      </GlassPanel>

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

      <GlassPanel title="Alpha Factory" icon={<FlaskConical className="h-4 w-4" />}>
        <div className="grid gap-3 md:grid-cols-4 text-xs">
          <div>
            <p className="text-slate-500 uppercase text-[10px]">Paper entry</p>
            <p className={alpha.can_trade_paper_now ? "text-emerald-300 font-semibold" : "text-amber-300 font-semibold"}>
              {alpha.can_trade_paper_now ? "evidence ready" : "blocked"}
            </p>
          </div>
          <div>
            <p className="text-slate-500 uppercase text-[10px]">Candidates</p>
            <p className="text-white font-semibold">{alpha.paper_candidate_count ?? 0}</p>
          </div>
          <div>
            <p className="text-slate-500 uppercase text-[10px]">Rejected</p>
            <p className="text-white font-semibold">{alpha.rejected_strategy_count ?? 0}</p>
          </div>
          <div>
            <p className="text-slate-500 uppercase text-[10px]">Best setup</p>
            <p className="text-white font-semibold">{alpha.best_candidate?.symbol ?? "none"}</p>
          </div>
        </div>
        <p className="mt-3 text-[11px] text-slate-400">
          {alpha.plain_english ??
            alpha.autonomous_status?.plain_english ??
            "No alpha scorecards yet. Research must produce evidence before paper entry."}
        </p>
      </GlassPanel>

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
