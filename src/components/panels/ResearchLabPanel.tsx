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
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });

  const [strategyId, setStrategyId] = useState("crypto_push_pull");
  const [symbols, setSymbols] = useState("BTC/USD,DOGE/USD");

  const load = useCallback(async () => {
    setLoading(true);
    const [st, cov, r, lb, rej, mem, strat] = await Promise.all([
      apiGet<LabStatus>("/api/lab/status"),
      apiGet<{ coverage?: Record<string, unknown>[] }>("/api/lab/historical-coverage"),
      apiGet<{ runs?: Record<string, unknown>[] }>("/api/lab/backtest/runs"),
      apiGet<{ leaderboard?: Record<string, unknown>[] }>("/api/lab/leaderboard"),
      apiGet<{ rejected?: Record<string, unknown>[] }>("/api/lab/rejected-strategies"),
      apiGet<{ memories?: Record<string, unknown>[] }>("/api/lab/research-memories"),
      apiGet<{ strategies?: Record<string, unknown>[] }>("/api/lab/strategies"),
    ]);
    if (st.ok) setStatus(st.data as LabStatus);
    setCoverage(cov.data?.coverage || []);
    setRuns(r.data?.runs || []);
    setLeaderboard(lb.data?.leaderboard || []);
    setRejected(rej.data?.rejected || []);
    setMemories(mem.data?.memories || []);
    setStrategies(strat.data?.strategies || []);
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
    await apiPost("/api/lab/backtest/batch-run", {
      strategy_id: strategyId,
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
    });
    await load();
    setBusy(false);
  }

  async function runResearchNow() {
    setBusy(true);
    await apiPost("/api/lab/research/run", {
      strategy_families: [strategyId],
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
    });
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
                <th>Start</th>
                <th>End</th>
                <th>Gaps</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map((c) => (
                <tr key={`${c.symbol}-${c.timeframe}`} className="text-slate-300 border-t border-white/5">
                  <td className="py-1">{String(c.symbol)}</td>
                  <td>{String(c.timeframe)}</td>
                  <td>{String(c.rows_count)}</td>
                  <td>{String(c.start_date ?? "—")}</td>
                  <td>{String(c.end_date ?? "—")}</td>
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
              <li key={String(row.parameter_set_id)} className="flex justify-between text-slate-300">
                <span>{String(row.strategy_id)}</span>
                <span className="text-emerald-400">E {String(row.expectancy)}</span>
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
