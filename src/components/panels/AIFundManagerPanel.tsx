"use client";

import { useState } from "react";
import { Brain, CheckCircle2, Pause } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { ConfidenceGauge } from "@/components/ui/ConfidenceGauge";
import { EmptyState } from "@/components/ui/EmptyState";
import { DecisionDrilldownModal, type DrillType } from "@/components/panels/DecisionDrilldownModal";
import type { AIFundManagerData } from "@/types/dashboard";

interface AIFundManagerPanelProps {
  data: AIFundManagerData;
}

export function AIFundManagerPanel({ data }: AIFundManagerPanelProps) {
  const [drill, setDrill] = useState<DrillType | null>(null);

  const badgeClass =
    data.status === "active"
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
      : data.status === "stale" || data.status === "skipped"
        ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
        : "bg-slate-500/15 text-slate-400 border-slate-500/30";

  const statBtn =
    "cursor-pointer hover:bg-white/5 rounded transition text-center w-full";

  return (
    <>
      <GlassPanel
        title="Strategy Reviewer"
        icon={<Brain className="h-4 w-4" />}
        action={
          <span className={`rounded px-2 py-0.5 text-[10px] font-bold tracking-wider border uppercase ${badgeClass}`}>
            {data.status === "active" ? "ACTIVE" : data.status.replace("_", " ").toUpperCase()}
          </span>
        }
        className="h-full"
      >
        {data.status === "not_configured" ? (
          <EmptyState message={data.message ?? "Gemini not configured"} />
        ) : (
          <>
            <section className="grid grid-cols-[1fr_auto] gap-4 mb-4">
              <article className="rounded-lg border border-hive-cyan/25 bg-hive-cyan/5 p-4">
                <header className="flex items-center gap-2 mb-1">
                  <Pause className="h-5 w-5 text-hive-cyan" />
                  <span className="text-2xl font-bold tracking-wider text-white">{data.decision ?? "—"}</span>
                </header>
                <p className="text-xs text-slate-400">{data.decisionMessage}</p>
              </article>
              {data.confidence !== null ? (
                <ConfidenceGauge value={data.confidence} label={data.confidenceLabel} />
              ) : (
                <EmptyState message="No confidence score" className="py-4 px-2" />
              )}
            </section>
            <section className="mb-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Reason Summary</p>
              <p className="text-xs leading-relaxed text-slate-300">{data.reasonSummary}</p>
            </section>
            {(data.whatILearned?.length || data.whatIWillAvoid?.length) && (
              <section className="mb-3 space-y-2 text-[10px]">
                {data.whatILearned && data.whatILearned.length > 0 && (
                  <div>
                    <p className="text-cyan-400 font-semibold mb-0.5">Evidence learned</p>
                    <ul className="text-slate-400 list-disc pl-4">
                      {data.whatILearned.slice(0, 4).map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {data.whatIWillAvoid && data.whatIWillAvoid.length > 0 && (
                  <div>
                    <p className="text-amber-400 font-semibold mb-0.5">Patterns to avoid</p>
                    <ul className="text-slate-400 list-disc pl-4">
                      {data.whatIWillAvoid.slice(0, 4).map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {data.whatIWillTestNext && data.whatIWillTestNext.length > 0 && (
                  <div>
                    <p className="text-violet-400 font-semibold mb-0.5">Next tests queued</p>
                    <ul className="text-slate-400 list-disc pl-4">
                      {data.whatIWillTestNext.slice(0, 3).map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {data.currentOpenPositionConcern && data.currentOpenPositionConcern.length > 0 && (
                  <div>
                    <p className="text-red-300 font-semibold mb-0.5">Open position concern</p>
                    <ul className="text-slate-400 list-disc pl-4">
                      {data.currentOpenPositionConcern.map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}
            <section className="flex items-center gap-2 mb-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20 px-3 py-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
              <span className="text-xs text-emerald-400">
                {data.approvalStatus}: {data.approvalMessage}
              </span>
            </section>
          </>
        )}
        <section className="grid grid-cols-4 gap-2">
          {[
            { label: "Decisions Today", value: data.stats.decisionsToday, drill: null as DrillType | null },
            { label: "Approved", value: data.stats.approved, drill: "approved" as DrillType, color: "text-emerald-400" },
            { label: "Blocked", value: data.stats.blocked, drill: "blocked" as DrillType, color: "text-red-400" },
            {
              label: "Lessons",
              value: data.stats.learnedLessons,
              drill: "lessons" as DrillType,
              color: "text-hive-cyan",
            },
          ].map((stat) => (
            <article key={stat.label} className="rounded-lg border border-white/5 bg-white/2 px-2 py-2">
              {stat.drill ? (
                <button type="button" className={statBtn} onClick={() => setDrill(stat.drill)}>
                  <p className={`text-lg font-bold ${stat.color ?? "text-white"}`}>{stat.value}</p>
                  <p className="text-[9px] text-slate-500 leading-tight">{stat.label}</p>
                </button>
              ) : (
                <>
                  <p className="text-lg font-bold text-white text-center">{stat.value}</p>
                  <p className="text-[9px] text-slate-500 leading-tight text-center">{stat.label}</p>
                </>
              )}
            </article>
          ))}
        </section>
        {(data.stats.ordersSubmitted ?? 0) > 0 && (
          <button
            type="button"
            className="mt-2 w-full text-xs text-hive-cyan border border-hive-cyan/20 rounded py-1.5 hover:bg-hive-cyan/5"
            onClick={() => setDrill("orders")}
          >
            Orders submitted: {data.stats.ordersSubmitted} — view execution logs
          </button>
        )}
      </GlassPanel>
      <DecisionDrilldownModal type={drill} onClose={() => setDrill(null)} />
    </>
  );
}
