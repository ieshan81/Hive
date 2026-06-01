"use client";

import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Play, Pause, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type AlphaStatus = {
  can_trade_paper_now?: boolean;
  reason?: string;
  plain_english?: string;
  paper_candidate_count?: number;
  rejected_strategy_count?: number;
  unproven_strategy_count?: number;
  best_candidate?: Record<string, unknown> | null;
  autonomous_scheduler?: {
    enabled?: boolean;
    last_run_status?: string;
    skipped_reason?: string;
    next_run_due_at?: string | null;
    backtests_run?: number;
    memory_written_count?: number;
  };
  session_research?: {
    session_scorecard_count?: number;
    closest_session_candidate?: Record<string, unknown> | null;
    plain_english?: string;
  };
};

type Scorecards = { scorecards?: Record<string, unknown>[] };

function label(value: unknown) {
  return String(value ?? "-").replace(/_/g, " ");
}

function time(value: unknown) {
  if (!value) return "-";
  return String(value).replace("T", " ").replace("Z", "").slice(0, 16);
}

export function AlphaFactoryPanel({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState<AlphaStatus | null>(null);
  const [scorecards, setScorecards] = useState<Record<string, unknown>[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [st, cards] = await Promise.all([
      apiGet<AlphaStatus>("/api/alpha-factory/status", { timeoutMs: 5000 }),
      apiGet<Scorecards>("/api/alpha-factory/scorecards?limit=8", { timeoutMs: 5000 }),
    ]);
    if (st.ok) setStatus(st.data);
    if (cards.ok) setScorecards(cards.data?.scorecards || []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(endpoint: string, labelText: string) {
    setBusy(labelText);
    const res = await apiPostOperator(endpoint, { actor: "operator", force: true });
    setMessage(res.ok ? `${labelText} completed. No orders were submitted.` : res.error || "Action failed");
    await load();
    setBusy(null);
  }

  const best = status?.best_candidate || null;
  const scheduler = status?.autonomous_scheduler || {};

  return (
    <GlassPanel title="Autonomous Alpha Factory" icon={<BrainCircuit className="h-4 w-4" />}>
      <p className="text-xs text-slate-400">
        {status?.plain_english || "Research-only alpha governance has not run yet."}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] md:grid-cols-4">
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Paper entry</p>
          <p className={status?.can_trade_paper_now ? "text-emerald-300" : "text-amber-300"}>
            {status?.can_trade_paper_now ? "Allowed" : "Blocked"}
          </p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Candidates</p>
          <p className="text-slate-200">{String(status?.paper_candidate_count ?? 0)}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Rejected</p>
          <p className="text-slate-200">{String(status?.rejected_strategy_count ?? 0)}</p>
        </div>
        <div className="rounded border border-white/10 p-2">
          <p className="text-slate-500 uppercase">Scheduler</p>
          <p className={scheduler.enabled ? "text-emerald-300" : "text-slate-400"}>
            {scheduler.enabled ? "On" : "Paused"}
          </p>
        </div>
      </div>

      <div className="mt-2 rounded border border-cyan-300/20 bg-cyan-300/5 p-2 text-[10px] text-cyan-100">
        <p className="uppercase tracking-wide text-cyan-300/80">Session research</p>
        <p>{status?.session_research?.plain_english || "Session evidence not built yet."}</p>
      </div>

      <div className="mt-3 rounded-lg border border-white/10 bg-black/20 p-3 text-xs">
        <p className="text-white">
          Best: {best ? `${String(best.symbol)} · ${label(best.strategy_family)} · ${label(best.verdict)}` : "none"}
        </p>
        <p className="mt-1 text-slate-500">
          Reason: {label(status?.reason)} · Next due {time(scheduler.next_run_due_at)}
        </p>
      </div>

      {!compact ? (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!!busy}
              onClick={() => run("/api/alpha-factory/run-cycle", "Alpha cycle")}
              className="inline-flex items-center gap-1 rounded border border-hive-cyan/30 bg-hive-cyan/10 px-3 py-1.5 text-[10px] text-hive-cyan disabled:opacity-50"
            >
              <Play className="h-3 w-3" /> Run research cycle
            </button>
            <button
              type="button"
              disabled={!!busy}
              onClick={() => run("/api/alpha-factory/pause", "Pause")}
              className="inline-flex items-center gap-1 rounded border border-white/10 px-3 py-1.5 text-[10px] text-slate-300 disabled:opacity-50"
            >
              <Pause className="h-3 w-3" /> Pause
            </button>
            <button
              type="button"
              disabled={!!busy}
              onClick={load}
              className="inline-flex items-center gap-1 rounded border border-white/10 px-3 py-1.5 text-[10px] text-slate-300 disabled:opacity-50"
            >
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>
          </div>
          {message ? <p className="mt-2 text-[10px] text-slate-500">{message}</p> : null}
          <ul className="mt-3 max-h-40 space-y-1 overflow-auto text-[10px] text-slate-400">
            {scorecards.map((row) => (
              <li key={String(row.id)} className="rounded border border-white/5 px-2 py-1">
                <span className="text-slate-200">{String(row.symbol)}</span> · {label(row.strategy_family)} ·{" "}
                <span className={row.verdict === "paper_candidate" ? "text-emerald-300" : "text-amber-300"}>
                  {label(row.verdict)}
                </span>{" "}
                · PF {String(row.profit_factor ?? "-")} · E {String(row.expectancy ?? "-")}
                {row.best_session ? (
                  <span className="text-cyan-300">
                    {" "}· {label(row.best_session)} edge {String(row.session_edge_after_cost_bps ?? "-")} bps
                  </span>
                ) : null}
              </li>
            ))}
            {!scorecards.length ? <li>No alpha scorecards yet. Run the Alpha cycle after market data is cached.</li> : null}
          </ul>
        </>
      ) : null}
    </GlassPanel>
  );
}
