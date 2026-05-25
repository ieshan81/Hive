"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, Play, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { PanelError } from "@/components/ui/PanelError";
import { apiGet, apiPost } from "@/lib/apiClient";
import type { PanelLoadMeta } from "@/types/api";

type LabStatus = {
  auto_backtest_enabled?: boolean;
  backtest_run_count?: number;
  historical_coverage_symbols?: number;
  monte_carlo?: { status?: string; message?: string; warning?: string };
};

export function ResearchLabPanel() {
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [coverage, setCoverage] = useState<Record<string, unknown>[]>([]);
  const [runs, setRuns] = useState<Record<string, unknown>[]>([]);
  const [leaderboard, setLeaderboard] = useState<Record<string, unknown>[]>([]);
  const [rejected, setRejected] = useState<Record<string, unknown>[]>([]);
  const [memories, setMemories] = useState<Record<string, unknown>[]>([]);
  const [strategies, setStrategies] = useState<Record<string, unknown>[]>([]);
  const [strategyDefs, setStrategyDefs] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [batchSummary, setBatchSummary] = useState<Record<string, unknown> | null>(null);
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });

  const [strategyId, setStrategyId] = useState("crypto_push_pull");
  const [symbols, setSymbols] = useState("BTC/USD,DOGE/USD");

  const load = useCallback(async () => {
    setLoading(true);
    const [st, cov, r, lb, rej, mem, strat, defs] = await Promise.all([
      apiGet<LabStatus>("/api/lab/status"),
      apiGet<{ coverage?: Record<string, unknown>[] }>("/api/lab/historical-coverage"),
      apiGet<{ runs?: Record<string, unknown>[] }>("/api/lab/backtest/runs"),
      apiGet<{ leaderboard?: Record<string, unknown>[] }>("/api/lab/strategy-leaderboard"),
      apiGet<{ rejected?: Record<string, unknown>[] }>("/api/lab/rejected-strategies"),
      apiGet<{ memories?: Record<string, unknown>[] }>("/api/lab/research-memories"),
      apiGet<{ strategies?: Record<string, unknown>[] }>("/api/lab/strategies"),
      apiGet<{ strategies?: Record<string, unknown>[] }>("/api/lab/strategy-definitions"),
    ]);
    if (st.ok) setStatus(st.data as LabStatus);
    setCoverage(cov.data?.coverage || []);
    setRuns(r.data?.runs || []);
    setLeaderboard(lb.data?.leaderboard || []);
    setRejected(rej.data?.rejected || []);
    setMemories(mem.data?.memories || []);
    setStrategies(strat.data?.strategies || []);
    setStrategyDefs(defs.data?.strategies || strat.data?.strategies || []);
    setMeta({
      source: st.ok ? "live_api" : "empty",
      lastUpdated: new Date().toISOString(),
      endpoint: "/api/lab/status",
      httpStatus: st.status,
      error: st.error || undefined,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runBacktest() {
    setBusy(true);
    await apiPost("/api/lab/backtest/run", {
      strategy_id: strategyId,
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
    });
    await load();
    setBusy(false);
  }

  async function runBatch() {
    setBusy(true);
    const res = await apiPost<Record<string, unknown>>("/api/lab/backtest/batch-run", {
      strategy_family: strategyId,
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
      timeframe: "1h",
      lookback_days: 90,
    });
    if (res.ok && res.data) {
      setBatchSummary(res.data);
      setLastAction("Batch sweep completed");
    } else {
      setBatchSummary(null);
      setLastAction(res.error || "batch failed");
    }
    await load();
    setBusy(false);
  }

  async function runResearchNow() {
    setBusy(true);
    const res = await apiPost("/api/lab/research/run", {
      strategy_families: [strategyId],
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
      force: true,
    });
    setLastAction(res.data ? JSON.stringify(res.data).slice(0, 120) : res.error || "done");
    await load();
    setBusy(false);
  }

  async function fetchData() {
    setBusy(true);
    await apiPost("/api/lab/data/fetch", {
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
      timeframes: ["1h"],
      lookback_days: 90,
    });
    await apiPost("/api/lab/strategies/seed", {});
    await load();
    setBusy(false);
  }

  async function seedStrategies() {
    setBusy(true);
    await apiPost("/api/lab/strategies/seed", {});
    await load();
    setBusy(false);
  }

  async function runWalkForward() {
    setBusy(true);
    await apiPost("/api/lab/walk-forward/run", {
      strategy_id: strategyId,
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
    });
    await load();
    setBusy(false);
  }

  const mc = status?.monte_carlo;
  const batchAnalysis =
    batchSummary?.batch_analysis && typeof batchSummary.batch_analysis === "object"
      ? (batchSummary.batch_analysis as Record<string, unknown>)
      : null;
  const paramVariationWarning =
    typeof batchAnalysis?.parameter_variation_warning === "string"
      ? batchAnalysis.parameter_variation_warning
      : null;

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-5 w-5 text-violet-400" />
          <h2 className="text-lg font-semibold text-white">Autonomous Research Lab</h2>
        </div>
        <button
          type="button"
          onClick={load}
          className="text-xs text-hive-cyan flex items-center gap-1 border border-hive-cyan/30 rounded px-2 py-1"
        >
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </header>

      {meta.error && (
        <PanelError title="Lab API failed" meta={meta} expectedShape="{ status, backtest_run_count }" />
      )}

      {runs.length === 0 && !loading && (
        <p className="text-sm text-amber-400/90 border border-amber-500/20 rounded-lg px-3 py-2">
          No research runs yet — fetch Alpaca bars, then Run Batch Backtest or Run Research Lab Now.
        </p>
      )}
      {lastAction && <p className="text-[10px] text-slate-500 font-mono">{lastAction}</p>}

      {batchSummary && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-950/30 px-3 py-2 text-xs space-y-1">
          {Boolean(batchSummary.batch_failed_after_costs) && (
            <p className="text-amber-300 font-medium">Latest batch failed after costs</p>
          )}
          {batchSummary.promote_allowed === false && (
            <p className="text-red-300">Do not promote — metrics below research gates</p>
          )}
          {typeof batchSummary.coverage === "object" && batchSummary.coverage !== null && (
            <p className="text-slate-400">
              Data range used:{" "}
              {Object.values(batchSummary.coverage as Record<string, Record<string, string>>)
                .map((c) => `${c.actual_start_date ?? "?"} to ${c.actual_end_date ?? "?"}`)
                .join("; ") || "—"}
            </p>
          )}
          {typeof batchSummary.date_warning === "string" && batchSummary.date_warning && (
            <p className="text-amber-400">Requested 90 days but actual data is older — {batchSummary.date_warning}</p>
          )}
          {paramVariationWarning && (
              <p className="text-violet-300">
                Parameter sweep produced repeated identical results — inspect edge_multiplier, max_hold, ATR, spread
                caps.
              </p>
            )}
        </div>
      )}

      <GlassPanel title="Strategy definitions">
        <ul className="text-[10px] text-slate-400 max-h-24 overflow-y-auto space-y-0.5">
          {strategyDefs.map((s) => (
            <li key={String(s.strategy_id)}>
              <span className="text-violet-300">{String(s.strategy_id)}</span> — {String(s.strategy_name)}
            </li>
          ))}
          {!strategyDefs.length && <li>No definitions — click Seed strategies</li>}
        </ul>
        <button
          type="button"
          onClick={seedStrategies}
          className="mt-2 text-[10px] text-hive-cyan border border-hive-cyan/30 rounded px-2 py-1"
        >
          Seed strategies
        </button>
      </GlassPanel>

      <GlassPanel title="Research controls (no trading orders)">
        <p className="text-[10px] text-slate-500 mb-3">
          Paper-only cage — research never submits broker orders. Auto-backtest:{" "}
          {status?.auto_backtest_enabled ? "ON" : "OFF (default)"}.
        </p>
        <div className="grid md:grid-cols-2 gap-2 text-xs mb-3">
          <label className="text-slate-400">
            Strategy
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              className="block w-full mt-1 bg-slate-800 border border-white/10 rounded px-2 py-1.5 text-white"
            >
              {strategies.map((s) => (
                <option key={String(s.strategy_id)} value={String(s.strategy_id)}>
                  {String(s.strategy_name)}
                </option>
              ))}
              {!strategies.length && <option value="crypto_push_pull">Crypto Push-Pull</option>}
            </select>
          </label>
          <label className="text-slate-400">
            Symbols (comma-separated)
            <input
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              className="block w-full mt-1 bg-slate-800 border border-white/10 rounded px-2 py-1.5 text-white"
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={runBacktest}
            className="flex items-center gap-1 px-3 py-1.5 rounded bg-violet-600/80 text-white text-xs"
          >
            <Play className="h-3 w-3" /> Run backtest
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={runBatch}
            className="px-3 py-1.5 rounded border border-violet-500/40 text-violet-300 text-xs"
          >
            Parameter sweep
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={runWalkForward}
            className="px-3 py-1.5 rounded border border-indigo-500/40 text-indigo-300 text-xs"
          >
            Walk-forward
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={fetchData}
            className="px-3 py-1.5 rounded border border-white/10 text-slate-300 text-xs"
          >
            Fetch historical data
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={runResearchNow}
            className="px-3 py-1.5 rounded border border-hive-cyan/40 text-hive-cyan text-xs"
          >
            Run Research Lab Now
          </button>
        </div>
      </GlassPanel>

      <GlassPanel title="Historical data coverage">
        {loading ? (
          <p className="text-xs text-slate-500">Loading…</p>
        ) : coverage.length === 0 ? (
          <p className="text-xs text-slate-500">No cached coverage — run a backtest to fetch Alpaca bars.</p>
        ) : (
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left py-1">Symbol</th>
                <th>TF</th>
                <th>Rows</th>
                <th>Actual range</th>
                <th>Stale</th>
                <th>Gaps</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map((c) => (
                <tr key={`${c.symbol}-${c.timeframe}`} className="text-slate-300 border-t border-white/5">
                  <td className="py-1">{String(c.symbol)}</td>
                  <td>{String(c.timeframe)}</td>
                  <td>{String(c.rows_count)}</td>
                  <td>
                    {String(c.actual_start_date ?? c.start_date ?? "—")} →{" "}
                    {String(c.actual_end_date ?? c.end_date ?? "—")}
                  </td>
                  <td className={c.data_is_recent === false ? "text-amber-400" : ""}>
                    {c.data_staleness_days != null ? `${String(c.data_staleness_days)}d` : "—"}
                  </td>
                  <td>{c.gaps_detected ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </GlassPanel>

      <div className="grid lg:grid-cols-2 gap-4">
        <GlassPanel title="Backtest runs">
          <ul className="text-xs space-y-2 max-h-48 overflow-y-auto">
            {runs.map((run) => (
              <li key={String(run.run_id ?? run.id)} className="border-b border-white/5 pb-2">
                <span className="text-white font-medium">{String(run.strategy_id)}</span>
                <span className="text-slate-500 ml-2">{String(run.status)}</span>
                <p className="text-slate-500">
                  trades {String(run.num_trades)} · conf {String(run.confidence_label)}
                </p>
              </li>
            ))}
            {!runs.length && !loading && <li className="text-slate-500">No runs yet</li>}
          </ul>
        </GlassPanel>

        <GlassPanel title="Strategy leaderboard">
          <ul className="text-xs space-y-1 max-h-48 overflow-y-auto">
            {leaderboard.map((row) => (
              <li key={String(row.parameter_set_id)} className="border-b border-white/5 pb-1 text-slate-300">
                <div className="flex justify-between">
                  <span>{String(row.strategy_id)}</span>
                  <span className={row.promote_allowed ? "text-emerald-400" : "text-red-400"}>
                    E {String(row.expectancy)}
                  </span>
                </div>
                <p className="text-[10px] text-slate-500">
                  {String(row.recommended_action)} · promote {row.promote_allowed ? "yes" : "no"}
                  {row.rejection_reason ? ` · ${String(row.rejection_reason)}` : ""}
                </p>
                {typeof row.data_warning === "string" && row.data_warning ? (
                  <p className="text-[10px] text-amber-500">{row.data_warning}</p>
                ) : null}
                {typeof row.parameter_variation_warning === "string" && row.parameter_variation_warning ? (
                  <p className="text-[10px] text-violet-400">{row.parameter_variation_warning}</p>
                ) : null}
              </li>
            ))}
            {!leaderboard.length && <li className="text-slate-500">Need parameter sweeps with 5+ trades</li>}
          </ul>
        </GlassPanel>
      </div>

      <GlassPanel title="Rejected strategies">
        <ul className="text-xs text-slate-400 space-y-1">
          {rejected.map((r) => (
            <li key={String(r.strategy_id)}>
              {String(r.strategy_id)}: {String(r.rejection_reason ?? "—")}
            </li>
          ))}
          {!rejected.length && <li>None</li>}
        </ul>
      </GlassPanel>

      <GlassPanel title="Research memories">
        <ul className="text-xs space-y-2 max-h-40 overflow-y-auto">
          {memories.map((m) => (
            <li key={String(m.lesson_id ?? m.node_id)} className="text-slate-300">
              <span className="text-violet-300">{String(m.title)}</span>
              <p className="text-slate-500 truncate">{String(m.summary)}</p>
            </li>
          ))}
          {!memories.length && <li className="text-slate-500">Run backtests to create research memories</li>}
        </ul>
      </GlassPanel>

      <GlassPanel title="Monte Carlo (real closed trades only)">
        <p className="text-xs text-slate-400">
          Status: {mc?.status ?? "—"}
          {mc?.message && ` — ${mc.message}`}
          {mc?.warning && ` — ${mc.warning}`}
        </p>
        <p className="text-[10px] text-slate-600 mt-1">No synthetic paths — requires ≥10 closed trades in DB.</p>
      </GlassPanel>
    </section>
  );
}
