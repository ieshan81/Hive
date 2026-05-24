"use client";

import { Brain, CheckCircle2, Pause } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { ConfidenceGauge } from "@/components/ui/ConfidenceGauge";
import { EmptyState } from "@/components/ui/EmptyState";
import type { AIFundManagerData } from "@/types/dashboard";

interface AIFundManagerPanelProps {
  data: AIFundManagerData;
}

export function AIFundManagerPanel({ data }: AIFundManagerPanelProps) {
  const badgeClass =
    data.status === "active"
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
      : "bg-slate-500/15 text-slate-400 border-slate-500/30";

  return (
    <GlassPanel
      title="AI Fund Manager"
      icon={<Brain className="h-4 w-4" />}
      action={
        <span className={`rounded px-2 py-0.5 text-[10px] font-bold tracking-wider border uppercase ${badgeClass}`}>
          {data.status === "active" ? "ACTIVE" : data.status.replace("_", " ")}
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
              <EmptyState message="No confidence score yet" className="py-4 px-2" />
            )}
          </section>
          <section className="mb-3">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Reason Summary</p>
            <p className="text-xs leading-relaxed text-slate-300">{data.reasonSummary}</p>
          </section>
          {data.memoryUsedPct !== null && (
            <section className="mb-3">
              <header className="flex justify-between text-[10px] mb-1">
                <span className="text-slate-500">Memory Used</span>
                <span className="text-hive-cyan">{data.memoryUsedPct}%</span>
              </header>
              <figure className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                <span className="block h-full rounded-full bg-gradient-to-r from-hive-cyan to-hive-violet" style={{ width: `${data.memoryUsedPct}%` }} />
              </figure>
            </section>
          )}
          <section className="flex items-center gap-2 mb-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20 px-3 py-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
            <span className="text-xs text-emerald-400">{data.approvalStatus}: {data.approvalMessage}</span>
          </section>
        </>
      )}
      <section className="grid grid-cols-4 gap-2">
        {[
          { label: "Decisions Today", value: data.stats.decisionsToday },
          { label: "Approved", value: data.stats.approved, color: "text-emerald-400" },
          { label: "Blocked", value: data.stats.blocked, color: "text-red-400" },
          { label: "Learned Lessons", value: data.stats.learnedLessons },
        ].map((stat) => (
          <article key={stat.label} className="rounded-lg border border-white/5 bg-white/2 px-2 py-2 text-center">
            <p className={`text-lg font-bold ${stat.color ?? "text-white"}`}>{stat.value}</p>
            <p className="text-[9px] text-slate-500 leading-tight">{stat.label}</p>
          </article>
        ))}
      </section>
    </GlassPanel>
  );
}
