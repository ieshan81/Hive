"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, FlaskConical, LineChart, Sparkles, Network } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";
import { onHiveNukeComplete } from "@/lib/hiveRefresh";

type StrategyLab = Record<string, unknown>;
type UniverseDiscovery = {
  title?: string;
  available_usd_pairs?: number;
  eligible_for_backtest?: number;
  selected_symbols?: string[];
  tested_symbols?: string[];
  skipped_symbols?: Record<string, unknown>[];
  top_performers?: Record<string, unknown>[];
  weak_performers?: Record<string, unknown>[];
  strategy_verdict?: string;
  funnel_answer?: string;
  next_test_plan?: string;
  should_paper_trade_now?: boolean;
};
type BacktestLab = {
  backtest_run_count?: number;
  latest_run?: Record<string, unknown>;
  result_label?: string;
  ai_lesson?: Record<string, unknown>;
  universe_discovery?: UniverseDiscovery;
};
type AdvisorPanel = Record<string, unknown>;
type MemoryGraph = { validated_memories?: Record<string, unknown>[]; latest_useful_lesson?: Record<string, unknown> };

export function AIManagerLearningPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [sentiment, setSentiment] = useState<Record<string, unknown> | null>(null);
  const [showRawMemories, setShowRawMemories] = useState(false);

  const load = useCallback(async () => {
    const [st, sent] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/ai-manager/status"),
      apiGet<Record<string, unknown>>("/api/sentiment/status"),
    ]);
    if (st.ok) setStatus(st.data);
    if (sent.ok) setSentiment(sent.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(
    () =>
      onHiveNukeComplete(() => {
        setStatus(null);
        void load();
      }),
    [load]
  );

  const lab = (status?.strategy_lab as StrategyLab) || {};
  const bt = (status?.backtest_lab as BacktestLab) || {};
  const advisor = (status?.gemini_advisor as AdvisorPanel) || {};
  const graph = (status?.memory_graph as MemoryGraph) || {};
  const latestRun = bt.latest_run || {};
  const udisc = bt.universe_discovery || {};

  return (
    <section className="space-y-4 max-w-5xl">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Brain className="h-6 w-6 text-hive-cyan" />
        AI Manager
      </h1>
      <p className="text-sm text-slate-400">{String(status?.headline ?? "Learning from paper trades")}</p>

      <div className="grid gap-4 md:grid-cols-2">
        <GlassPanel title="Strategy Lab" icon={<LineChart className="h-4 w-4" />}>
          <ul className="text-sm space-y-1.5 text-slate-300">
            <li>
              <span className="text-slate-500">Active strategy:</span> {String(lab.active_strategy ?? "—")}
            </li>
            <li>
              <span className="text-slate-500">Version:</span> {String(lab.strategy_version ?? "—")}
            </li>
            <li>
              <span className="text-slate-500">Live scoring:</span> {String(lab.live_scoring_model ?? "—")}
            </li>
            <li>
              <span className="text-slate-500">Backtest result:</span> {String(lab.backtest_result ?? "none yet")}
            </li>
            <li>
              <span className="text-slate-500">Paper result:</span> {String(lab.paper_result ?? "—")}
            </li>
            <li>
              <span className="text-slate-500">Sample size:</span> {String(lab.sample_size ?? 0)}
            </li>
            <li>
              <span className="text-slate-500">Expectancy:</span> {String(lab.expectancy ?? "—")}
            </li>
            <li>
              <span className="text-slate-500">Status:</span>{" "}
              <span className="text-amber-300 capitalize">{String(lab.current_status ?? "unproven")}</span>
            </li>
            <li className="text-[11px] text-slate-500 pt-1">{String(lab.next_test_plan ?? "")}</li>
          </ul>
        </GlassPanel>

        <GlassPanel title="Backtest Lab" icon={<FlaskConical className="h-4 w-4" />}>
          <p className="text-sm text-white">Runs: {String(bt.backtest_run_count ?? 0)}</p>
          {latestRun.run_id ? (
            <ul className="mt-2 text-[11px] text-slate-400 space-y-1">
              <li>Run: {String(latestRun.run_id).slice(0, 8)}…</li>
              <li>Symbols: {JSON.stringify(latestRun.symbols)}</li>
              <li>Trades: {String(latestRun.num_trades)}</li>
              <li>Win rate: {String((latestRun.metrics as Record<string, unknown>)?.win_rate ?? latestRun.win_rate)}</li>
              <li>Expectancy: {String((latestRun.metrics as Record<string, unknown>)?.expectancy ?? latestRun.expectancy)}</li>
              <li>Profit factor: {String((latestRun.metrics as Record<string, unknown>)?.profit_factor ?? latestRun.profit_factor)}</li>
              <li>Drawdown: {String((latestRun.metrics as Record<string, unknown>)?.max_drawdown ?? latestRun.max_drawdown)}</li>
              <li>
                Result: <span className="text-hive-cyan">{String(bt.result_label ?? latestRun.result_label ?? "—")}</span>
              </li>
            </ul>
          ) : (
            <p className="text-sm text-slate-500 mt-2">No backtest runs yet. Operator can run push-pull backtest from Control Center.</p>
          )}
          {bt.ai_lesson && (
            <p className="text-[11px] text-slate-400 mt-2 border-t border-white/5 pt-2">
              AI lesson: {String((bt.ai_lesson as Record<string, unknown>).title ?? (bt.ai_lesson as Record<string, unknown>).summary)}
            </p>
          )}
          <div className="mt-4 border-t border-white/10 pt-3">
            <p className="text-xs font-semibold text-hive-cyan">{String(udisc.title ?? "Universe Discovery Backtest")}</p>
            <ul className="mt-2 text-[11px] text-slate-400 space-y-1">
              <li>USD pairs available: {String(udisc.available_usd_pairs ?? "—")}</li>
              <li>Eligible for backtest: {String(udisc.eligible_for_backtest ?? "—")}</li>
              <li>Selected: {JSON.stringify(udisc.selected_symbols ?? [])}</li>
              <li>Tested: {JSON.stringify(udisc.tested_symbols ?? [])}</li>
              <li>Verdict: <span className="text-amber-300 capitalize">{String(udisc.strategy_verdict ?? "not run")}</span></li>
              <li>Paper now: {udisc.should_paper_trade_now ? "yes" : "no"}</li>
            </ul>
            {udisc.funnel_answer && (
              <p className="text-[10px] text-slate-500 mt-2">{String(udisc.funnel_answer).slice(0, 280)}</p>
            )}
            {udisc.next_test_plan && (
              <p className="text-[10px] text-slate-500 mt-1">Next: {String(udisc.next_test_plan)}</p>
            )}
          </div>
        </GlassPanel>

        <GlassPanel title="Gemini Advisor" icon={<Sparkles className="h-4 w-4" />}>
          <p className="text-sm text-emerald-300/90">{String(advisor.display_title ?? "Gemini Advisor")}</p>
          <p className="text-[11px] text-slate-500 mt-1">{String(advisor.display_subtitle ?? advisor.role ?? "")}</p>
          <ul className="mt-2 text-[11px] text-slate-500 space-y-1">
            <li>Cannot trade: {advisor.cannot_trade ? "yes" : "no"}</li>
            <li>Cannot change live lock: {advisor.cannot_change_live_lock ? "yes" : "no"}</li>
            <li>Cannot apply config directly: {advisor.cannot_directly_apply_config ? "yes" : "no"}</li>
          </ul>
          {(() => {
            const review = advisor.latest_review as Record<string, unknown> | null | undefined;
            const summary = review?.summary;
            if (!summary) return null;
            return (
              <p className="text-xs text-slate-400 mt-2 border-t border-white/5 pt-2">
                Latest review: {String(summary).slice(0, 200)}
              </p>
            );
          })()}
        </GlassPanel>

        <GlassPanel title="Sentiment" icon={<Sparkles className="h-4 w-4 text-slate-500" />}>
          <p className="text-sm text-slate-400">{String(sentiment?.display_title ?? "Sentiment Intelligence: Not wired yet")}</p>
          <p className="text-[11px] text-slate-600 mt-1">{String(sentiment?.display_subtitle ?? "")}</p>
        </GlassPanel>

        <GlassPanel title="Memory Graph" icon={<Network className="h-4 w-4" />} className="md:col-span-2">
          <button
            type="button"
            onClick={() => setShowRawMemories((v) => !v)}
            className="text-[11px] text-hive-cyan mb-2"
          >
            {showRawMemories ? "Hide" : "Show"} raw events
          </button>
          {!showRawMemories && graph.latest_useful_lesson ? (
            <p className="text-sm text-white">
              Latest lesson: {String((graph.latest_useful_lesson as Record<string, unknown>).title ?? "—")}
            </p>
          ) : (
            <p className="text-sm text-slate-500">
              {String((graph as Record<string, unknown>).meaningful_memory_count ?? 0)} meaningful memories — raw events hidden by default.
            </p>
          )}
          <ul className="mt-2 max-h-48 overflow-y-auto space-y-1">
            {(graph.validated_memories ?? []).slice(0, 8).map((m) => (
              <li key={String(m.id)} className="text-[11px] text-slate-400 border-b border-white/5 pb-1">
                {String(m.title)}
              </li>
            ))}
          </ul>
        </GlassPanel>
      </div>
    </section>
  );
}
