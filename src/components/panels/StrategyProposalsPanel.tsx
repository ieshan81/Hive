"use client";

import { useCallback, useEffect, useState } from "react";
import { GitPullRequest } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator, checkServerOperatorProxy } from "@/lib/apiClient";
import { hasSessionOperatorToken } from "@/lib/operatorAuth";

type Proposal = {
  id: number;
  strategy_id: string;
  proposal_type: string;
  reason: string;
  status: string;
  expected_risk?: string;
  proposed_change?: Record<string, unknown>;
};

export function StrategyProposalsPanel() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [canMutate, setCanMutate] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<{ proposals?: Proposal[] }>("/api/strategy-proposals");
    if (r.ok) setProposals(r.data?.proposals || []);
  }, []);

  useEffect(() => {
    load();
    Promise.all([checkServerOperatorProxy(), Promise.resolve(hasSessionOperatorToken())]).then(
      ([proxy, session]) => setCanMutate(proxy || session)
    );
  }, [load]);

  async function approve(id: number) {
    if (!canMutate || !window.confirm("Apply this paper-safe proposal after review?")) return;
    setBusy(true);
    const r = await apiPostOperator(`/api/strategy-proposals/${id}/approve`, { operator: "ui" });
    setMsg(r.ok ? "Approved" : r.error || String(r.status));
    await load();
    setBusy(false);
  }

  async function reject(id: number) {
    if (!canMutate) return;
    setBusy(true);
    const r = await apiPostOperator(`/api/strategy-proposals/${id}/reject`, { operator: "ui" });
    setMsg(r.ok ? "Rejected" : r.error || String(r.status));
    await load();
    setBusy(false);
  }

  return (
    <GlassPanel title="Strategy Proposals" icon={<GitPullRequest className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Self-improvement suggestions from memory and confidence — operator approval required. Never changes live lock
        keys.
      </p>
      <ul className="space-y-2 max-h-96 overflow-y-auto">
        {proposals.length === 0 && <li className="text-[10px] text-slate-500">No proposals yet.</li>}
        {proposals.map((p) => (
          <li key={p.id} className="rounded border border-white/10 p-2 text-[10px]">
            <div className="font-medium text-slate-200">
              #{p.id} {p.strategy_id} · {p.proposal_type} · <span className="text-cyan-400">{p.status}</span>
            </div>
            <p className="text-slate-400 mt-1">{p.reason}</p>
            {p.expected_risk && <p className="text-slate-500 text-[9px]">Risk: {p.expected_risk}</p>}
            {p.status === "proposed" && (
              <div className="flex gap-2 mt-2">
                <button
                  type="button"
                  disabled={busy || !canMutate}
                  className="rounded bg-emerald-700/60 px-2 py-1 text-[9px] disabled:opacity-40"
                  onClick={() => approve(p.id)}
                >
                  Approve (paper-safe)
                </button>
                <button
                  type="button"
                  disabled={busy || !canMutate}
                  className="rounded border border-white/20 px-2 py-1 text-[9px] disabled:opacity-40"
                  onClick={() => reject(p.id)}
                >
                  Reject
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {msg && <p className="text-[10px] text-slate-400 mt-2">{msg}</p>}
    </GlassPanel>
  );
}
