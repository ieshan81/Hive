"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, AlertTriangle, RefreshCw, Activity } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";

type Dict = Record<string, unknown>;

type PositionPlan = {
  symbol?: string;
  qty?: number;
  entry_price?: number | null;
  current_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  trailing_stop?: number | null;
  max_hold_hours?: number | null;
  hard_safety_stop_price?: number | null;
  has_exit_plan?: boolean;
  missing_exit_plan?: boolean;
  exit_plan_source?: string;
  protection_state?: string;
  self_heal_attached_at?: string | null;
  emergency_backfill?: boolean;
  unrealized_pl?: number | null;
};

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  return String(v);
}

function protectionBadge(p: PositionPlan) {
  if (p.missing_exit_plan) {
    return <span className="text-rose-300">unmanaged</span>;
  }
  const state = p.protection_state || p.exit_plan_source || "protected";
  if (state === "emergency plan" || p.exit_plan_source === "emergency_backfill" || p.emergency_backfill) {
    return <span className="text-amber-300">emergency plan</span>;
  }
  if (state === "recovered plan" || p.exit_plan_source === "recovered_signal") {
    return <span className="text-cyan-300">recovered plan</span>;
  }
  return <span className="text-emerald-300">{state}</span>;
}

export function PositionMonitorPanel() {
  const [data, setData] = useState<Dict | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [canMutate, setCanMutate] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<Dict>("/api/push-pull/exit-monitor/status");
    if (r.ok && r.data) setData(r.data);
  }, []);

  useEffect(() => {
    load();
    Promise.all([checkServerOperatorProxy(), Promise.resolve(hasSessionOperatorToken())]).then(
      ([proxy, session]) => setCanMutate(proxy || session)
    );
  }, [load]);

  async function runNow() {
    if (!canMutate) {
      setMsg("Operator authorization required to run the exit monitor.");
      return;
    }
    setBusy(true);
    const r = await apiPostOperator("/api/paper-learning/monitor-exits", { operator: "ui" });
    setMsg(r.ok ? "Exit monitor run: ok" : `Exit monitor run: ${r.error ?? r.status}`);
    await load();
    setBusy(false);
  }

  const positions = (data?.positions as PositionPlan[]) || [];
  const anyMissing = Boolean(data?.any_missing_exit_plan);
  const missingSymbols = (data?.missing_exit_plan_symbols as string[]) || [];
  const openCount = Number(data?.open_positions_count ?? positions.length);
  const selfHeal = (data?.self_heal as Dict) || {};
  const healDiag = (data?.self_heal_diagnostics as Dict) || {};

  return (
    <GlassPanel title="Position Monitor" icon={<Activity className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Per-position exit plans (entry / stop / target / trailing / max-hold). Unmanaged positions trigger automatic
        self-heal each tick; emergency plans are paper-only backstops. Exits route through the cage — paper sells only.
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-3 text-[10px]">
        <span className="rounded-full border border-white/10 px-2.5 py-1 font-semibold text-slate-200">
          Open: {openCount}
        </span>
        {anyMissing ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 font-semibold text-rose-300">
            <AlertTriangle className="h-3 w-3" /> {missingSymbols.length} missing exit plan
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 font-semibold text-emerald-300">
            <ShieldCheck className="h-3 w-3" /> All managed
          </span>
        )}
        <span className="text-slate-500">Live: {data?.live_locked ? "LOCKED" : "—"}</span>
        <button
          type="button"
          disabled={busy || !canMutate}
          className="ml-auto rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={runNow}
        >
          Run exit monitor now
        </button>
        <button type="button" disabled={busy} className="rounded border border-white/10 px-2 py-1.5" onClick={() => load()}>
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      {Boolean(selfHeal.last_result || healDiag.last_self_heal_at) && (
        <div className="mb-3 rounded border border-white/10 bg-black/20 px-2 py-2 text-[10px] text-slate-400">
          <span className="text-slate-300 font-semibold">Self-heal: </span>
          {selfHeal.auto_heal_enabled === false ? "disabled" : "enabled"}
          {selfHeal.last_result ? ` · last ${String(selfHeal.last_result)}` : ""}
          {selfHeal.last_message ? ` — ${String(selfHeal.last_message)}` : ""}
          {selfHeal.last_attempt_at ? ` (${String(selfHeal.last_attempt_at)})` : ""}
          {typeof selfHeal.recovered_count === "number" || typeof selfHeal.emergency_count === "number" ? (
            <span>
              {" "}
              · recovered {String(selfHeal.recovered_count ?? 0)} / emergency {String(selfHeal.emergency_count ?? 0)}
            </span>
          ) : null}
          {typeof healDiag.unresolved_count === "number" && Number(healDiag.unresolved_count) > 0 ? (
            <span className="text-rose-300"> · {String(healDiag.unresolved_count)} unresolved</span>
          ) : null}
        </div>
      )}

      {positions.length === 0 ? (
        <p className="text-[10px] text-slate-500">No open positions — exit monitor idle.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead className="text-slate-500">
              <tr className="text-left">
                <th className="py-1 pr-2">Symbol</th>
                <th className="py-1 pr-2">Qty</th>
                <th className="py-1 pr-2">Entry</th>
                <th className="py-1 pr-2">Stop</th>
                <th className="py-1 pr-2">Target</th>
                <th className="py-1 pr-2">Trail</th>
                <th className="py-1 pr-2">Hard stop</th>
                <th className="py-1 pr-2">Protection</th>
              </tr>
            </thead>
            <tbody className="text-slate-300">
              {positions.map((p, i) => (
                <tr key={`${p.symbol}-${i}`} className="border-t border-white/5">
                  <td className="py-1 pr-2 font-semibold">{p.symbol}</td>
                  <td className="py-1 pr-2 tabular-nums">{fmt(p.qty)}</td>
                  <td className="py-1 pr-2 tabular-nums">{fmt(p.entry_price)}</td>
                  <td className="py-1 pr-2 tabular-nums">{fmt(p.stop_loss)}</td>
                  <td className="py-1 pr-2 tabular-nums">{fmt(p.take_profit)}</td>
                  <td className="py-1 pr-2 tabular-nums">{fmt(p.trailing_stop)}</td>
                  <td className="py-1 pr-2 tabular-nums">{fmt(p.hard_safety_stop_price)}</td>
                  <td className="py-1 pr-2">{protectionBadge(p)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {msg && <p className="text-[10px] text-slate-400 mt-2">{msg}</p>}
    </GlassPanel>
  );
}
