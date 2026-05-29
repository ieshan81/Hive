"use client";

import { useCallback, useEffect, useState } from "react";
import { FileCode, ShieldCheck } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet, apiPostOperator } from "@/lib/apiClient";

type CodeProposal = {
  proposal_id?: string;
  title?: string;
  status?: string;
  proposed_by_agent?: string;
  affected_files?: string[];
  tests_required?: string[];
  risk_assessment?: Record<string, unknown>;
};

export function CodeProposalsPanel() {
  const [proposals, setProposals] = useState<CodeProposal[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await apiGet<{ proposals?: CodeProposal[] }>("/api/research/code-proposals");
    if (r.ok) setProposals(r.data?.proposals || []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function approveDraft(id: string) {
    setBusy(true);
    const r = await apiPostOperator("/api/research/code-proposals/approve-draft", {
      actor: "operator",
      proposal_id: id,
    });
    setMsg(r.ok ? "Moved to human review. No files were changed." : r.error || String(r.status));
    await load();
    setBusy(false);
  }

  return (
    <GlassPanel title="Code Proposals" icon={<FileCode className="h-4 w-4" />}>
      <p className="mb-3 text-[10px] text-slate-500">
        AI may draft diffs and tests. It cannot apply, merge, deploy, or change live flags.
      </p>
      <ul className="max-h-80 space-y-2 overflow-auto text-[10px]">
        {!proposals.length ? <li className="text-slate-500">No code proposals yet.</li> : null}
        {proposals.map((p) => (
          <li key={p.proposal_id} className="rounded border border-white/10 p-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-slate-200">{p.title || p.proposal_id}</p>
                <p className="text-slate-500">
                  {p.proposed_by_agent || "research_os"} - {p.status || "draft"}
                </p>
              </div>
              <ShieldCheck className="h-4 w-4 text-emerald-300" />
            </div>
            <p className="mt-1 text-slate-400">
              Files: {(p.affected_files || []).slice(0, 3).join(", ") || "none listed"}
            </p>
            <p className="text-slate-500">
              Tests: {(p.tests_required || []).slice(0, 3).join(", ") || "not specified"}
            </p>
            {p.status === "draft" && p.proposal_id ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => approveDraft(String(p.proposal_id))}
                className="mt-2 rounded border border-hive-cyan/30 px-2 py-1 text-[9px] text-hive-cyan disabled:opacity-50"
              >
                Mark for human review
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {msg ? <p className="mt-2 text-[10px] text-slate-400">{msg}</p> : null}
    </GlassPanel>
  );
}

