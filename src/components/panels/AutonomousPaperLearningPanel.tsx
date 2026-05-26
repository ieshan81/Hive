"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, Play, Pause, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";

export function AutonomousPaperLearningPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [eligibility, setEligibility] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [eligError, setEligError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [canMutate, setCanMutate] = useState(false);

  const load = useCallback(async () => {
    const [st, elig] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/autonomous-paper-learning/status"),
      apiGet<Record<string, unknown>>("/api/account-pair-eligibility"),
    ]);
    if (st.ok) setStatus(st.data);
    if (elig.ok && elig.data) {
      setEligibility(elig.data);
      if (elig.data.status === "degraded") {
        setEligError(String(elig.data.plain_message || elig.data.message || "Eligibility degraded."));
      } else {
        setEligError(null);
      }
    } else {
      setEligError(elig.error || `Eligibility API failed (${elig.status})`);
    }
    window.dispatchEvent(new Event("hive:paper-learning-refresh"));
  }, []);

  useEffect(() => {
    load();
    Promise.all([checkServerOperatorProxy(), Promise.resolve(hasSessionOperatorToken())]).then(
      ([proxy, session]) => setCanMutate(proxy || session)
    );
  }, [load]);

  async function act(path: string, label: string, confirmMsg?: string) {
    if (!canMutate) {
      setMsg("Operator authorization required — configure server proxy or session token in Settings.");
      return;
    }
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(true);
    const r = await apiPostOperator(path, { operator: "ui" });
    setMsg(r.ok ? `${label}: ok` : `${label}: ${r.error ?? r.status}`);
    await load();
    setBusy(false);
  }

  const sched = (status?.scheduler as Record<string, unknown>) || {};
  const capacity = (status?.learning_capacity as Record<string, unknown>) || (status?.caps as Record<string, unknown>) || {};
  const allocator = (status?.capital_allocator as Record<string, unknown>) || {};
  const blockers = (status?.blockers as string[]) || [];
  const paperOn = Boolean(status?.paper_learning_on);

  return (
    <GlassPanel title="Autonomous Paper Learning" icon={<BookOpen className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Paper-only orchestration. Cron hits POST /tick — no in-process loop. Live trading stays locked.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Paper learning</div>
          <div className="font-semibold text-slate-200">{paperOn ? "ON" : "OFF"}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Can place paper orders</div>
          <div className="font-semibold">{status?.bot_can_place_paper_orders ? "YES" : "NO"}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Scheduler</div>
          <div className="font-semibold">{sched.scheduler_enabled ? "ON" : "OFF"}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Next tick (UTC)</div>
          <div className="font-semibold truncate">{String(sched.next_planned_at_utc || "—")}</div>
        </div>
      </div>

      {eligError && (
        <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-200">
          {eligError}
        </div>
      )}

      {blockers.length > 0 && (
        <ul className="text-[9px] text-amber-300/90 mb-2 list-disc pl-4">
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Paper trade frequency</div>
          <div className="font-semibold">{String(capacity.paper_trade_frequency || "opportunity_based")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Daily paper trade cap</div>
          <div className="font-semibold">
            {capacity.daily_paper_trade_cap == null ? "No fixed cap" : String(capacity.daily_paper_trade_cap)}
          </div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Position control</div>
          <div className="font-semibold">{String(capacity.position_control || "allocator_exposure")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Live trading</div>
          <div className="font-semibold text-rose-300/90">LOCKED</div>
        </div>
      </div>

      {allocator && (
        <div className="text-[9px] text-slate-500 mb-3">
          Allocator mode: {String(allocator.current_market_mode || "—")} · Deployable: $
          {String(allocator.deployable_capital ?? "—")} · Broker: {String(allocator.broker_data_freshness || "—")}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded bg-cyan-600/80 px-3 py-1.5 text-[10px] font-medium text-white disabled:opacity-40"
          onClick={() => act("/api/autonomous-paper-learning/enable", "Enable", "Enable autonomous paper learning?")}
        >
          Enable
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={() => act("/api/autonomous-paper-learning/pause", "Pause")}
        >
          <Pause className="inline h-3 w-3 mr-1" />
          Pause
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={() => act("/api/autonomous-paper-learning/run-one-cycle", "Run one cycle")}
        >
          <Play className="inline h-3 w-3 mr-1" />
          Run one paper cycle
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={() => act("/api/autonomous-paper-learning/run-backtest-lab-now", "Backtest lab")}
        >
          Run backtest lab
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded border border-rose-500/40 px-3 py-1.5 text-[10px] text-rose-300 disabled:opacity-40"
          onClick={() =>
            act(
              "/api/autonomous-paper-learning/disable-all-paper-trading",
              "Disable all paper",
              "Disable all paper trading and autonomous mode?"
            )
          }
        >
          Disable all paper trading
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded border border-white/10 px-2 py-1.5 text-[10px]"
          onClick={() => load()}
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4 border-t border-white/5 pt-3">
        <span className="text-[10px] text-slate-500 w-full">Scheduler (cron POST /tick)</span>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={() => act("/api/autonomous-paper-learning/scheduler/enable", "Scheduler enable")}
        >
          Enable scheduler
        </button>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={() => act("/api/autonomous-paper-learning/scheduler/pause", "Scheduler pause")}
        >
          Pause scheduler now
        </button>
        <span className="text-[9px] text-slate-500 self-center">
          Ticks today: {String(sched.ticks_today ?? 0)} · paused: {String(sched.paused_reason || "no")}
        </span>
      </div>

      {eligibility && (
        <div className="border-t border-white/5 pt-3">
          <h3 className="text-[10px] font-semibold text-slate-400 mb-2">Account / pair eligibility</h3>
          <p className="text-[9px] text-slate-500 mb-2">
            Eligible: {(eligibility.eligible as unknown[])?.length ?? eligibility.eligible_count ?? 0} · Blocked:{" "}
            {(eligibility.blocked as unknown[])?.length ?? eligibility.blocked_count ?? 0}
          </p>
          <ul className="text-[9px] text-slate-400 max-h-24 overflow-y-auto space-y-0.5">
            {((eligibility.blocked as { symbol?: string; reason?: string }[]) || []).slice(0, 8).map((b) => (
              <li key={b.symbol}>
                {b.symbol}: {b.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {msg && <p className="text-[10px] text-slate-400 mt-2">{msg}</p>}
    </GlassPanel>
  );
}
