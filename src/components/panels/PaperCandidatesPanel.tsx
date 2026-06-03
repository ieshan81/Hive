"use client";

import { useEffect, useState } from "react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { StrategyRegistryPanel } from "@/components/panels/StrategyRegistryPanel";
import { apiGet } from "@/lib/apiClient";

type Productivity = {
  paper_candidates?: number;
  scheduler_enabled?: boolean;
  why_no_paper_trade_plain?: string;
  current_best_candidate?: {
    symbol?: string;
    verdict?: string;
    edge_after_cost_bps?: number;
  };
  exact_next_blocker?: { code?: string; label?: string };
  missing_evidence?: string;
  stock_lane?: { mode?: string; stock_entries_allowed?: boolean };
};

export function PaperCandidatesPanel() {
  const [prod, setProd] = useState<Productivity | null>(null);

  useEffect(() => {
    apiGet<Productivity>("/api/paper-validation/productivity", { timeoutMs: 12000 }).then((res) => {
      if (res.ok) setProd(res.data ?? null);
    });
  }, []);

  const best = prod?.current_best_candidate;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-white">Paper Candidates</h1>
        <p className="mt-1 text-sm text-slate-400">What is close to a cage-approved paper broker trade</p>
      </header>

      <GlassPanel title="Pipeline summary">
        <p className="text-sm text-slate-300">{prod?.why_no_paper_trade_plain ?? "Loading productivity truth…"}</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3 text-[11px]">
          <div className="rounded border border-white/10 p-2">
            <p className="text-slate-500">Paper candidates</p>
            <p className="text-lg font-bold text-white">{prod?.paper_candidates ?? "—"}</p>
          </div>
          <div className="rounded border border-white/10 p-2">
            <p className="text-slate-500">Best setup</p>
            <p className="font-semibold text-hive-cyan">{best?.symbol ?? "—"}</p>
          </div>
          <div className="rounded border border-white/10 p-2">
            <p className="text-slate-500">Next blocker</p>
            <p className="text-white">{prod?.exact_next_blocker?.label ?? prod?.exact_next_blocker?.code ?? "—"}</p>
          </div>
        </div>
        {best ? (
          <p className="mt-2 text-xs text-slate-500">
            Verdict {best.verdict ?? "—"} · edge {best.edge_after_cost_bps ?? "—"} bps · stock lane{" "}
            {prod?.stock_lane?.mode ?? "—"}
          </p>
        ) : null}
        {prod?.missing_evidence ? (
          <p className="mt-2 text-xs text-amber-200/90">{prod.missing_evidence}</p>
        ) : null}
      </GlassPanel>

      <StrategyRegistryPanel />
    </div>
  );
}
