"use client";

import { useCallback, useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";

export function LivePromotionPanel() {
  const [checklist, setChecklist] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [canMutate, setCanMutate] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<Record<string, unknown>>("/api/live-promotion/checklist");
    if (r.ok) setChecklist(r.data);
  }, []);

  useEffect(() => {
    load();
    Promise.all([checkServerOperatorProxy(), Promise.resolve(hasSessionOperatorToken())]).then(
      ([proxy, session]) => setCanMutate(proxy || session)
    );
  }, [load]);

  const gaps = (checklist?.gaps as string[]) || [];
  const checks = (checklist?.checks as Record<string, boolean>) || {};
  const checkLabels: Record<string, string> = {
    live_lock_locked: "Live lock locked",
    paper_broker: "Paper broker",
    min_paper_days: "Minimum paper days",
    min_closed_trades: "Minimum closed trades",
    confidence_threshold: "Confidence threshold",
    market_calendar_ok: "Market calendar",
    pair_eligibility_ok: "Pair eligibility",
    positive_expectancy: "Positive expectancy",
  };
  const shiftAllowed = Boolean(checklist?.shift_to_live_allowed);
  const stage = String(checklist?.current_stage ?? "PAPER");

  async function validateCreds() {
    if (!canMutate) {
      setMsg("Operator token required.");
      return;
    }
    const r = await apiPostOperator("/api/live-promotion/validate-live-credentials", {});
    setMsg(r.ok ? JSON.stringify(r.data) : r.error || String(r.status));
  }

  async function requestShift() {
    if (!canMutate) return;
    const r = await apiPostOperator("/api/live-promotion/request-shift-to-live", { operator_note: "ui" });
    setMsg(r.ok ? JSON.stringify(r.data) : r.error || String(r.status));
    await load();
  }

  return (
    <GlassPanel title="Live Promotion" icon={<Lock className="h-4 w-4" />}>
      <p className="text-[10px] text-amber-300/90 mb-3">
        Live trading remains locked. This page shows readiness only — confidence cannot unlock live.
      </p>

      <div className="text-[11px] mb-3">
        Current stage: <span className="font-semibold text-cyan-300">{stage}</span>
      </div>

      <ul className="text-[10px] space-y-1 mb-4 max-h-64 overflow-y-auto">
        {Object.entries(checks).map(([id, passed]) => (
          <li key={id} className={passed ? "text-emerald-400" : "text-slate-400"}>
            {passed ? "✓" : "○"} {checkLabels[id] || id}
          </li>
        ))}
      </ul>

      {gaps.length > 0 && (
        <div className="text-[9px] text-slate-500 mb-3">
          <span className="font-semibold">Gaps:</span> {gaps.join("; ")}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!canMutate}
          title="Validates credentials only — no orders"
          className="rounded border border-white/20 px-3 py-1.5 text-[10px] disabled:opacity-40"
          onClick={validateCreds}
        >
          Add / verify live credentials (validate only)
        </button>
        <button
          type="button"
          disabled={!shiftAllowed || !canMutate}
          title={shiftAllowed ? "Opens checklist confirmation" : "Complete checklist first"}
          className="rounded bg-slate-700 px-3 py-1.5 text-[10px] disabled:opacity-30 disabled:cursor-not-allowed"
          onClick={requestShift}
        >
          Request shift to live
        </button>
      </div>

      {msg && <p className="text-[9px] text-slate-400 mt-2 break-all">{msg}</p>}
    </GlassPanel>
  );
}
