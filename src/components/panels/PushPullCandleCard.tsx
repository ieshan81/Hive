"use client";

import { GlassPanel } from "@/components/ui/GlassPanel";

type TickData = Record<string, unknown> | null;

const STEPS = [
  "Scanned",
  "Push signal",
  "Strategy check",
  "Allocator check",
  "Safety cage",
  "Quote refresh",
  "Paper submit",
  "Pull/exit watch",
  "Lesson saved",
] as const;

function pill(label: string, tone: "fresh" | "stale" | "neutral" | "good" | "warn") {
  const tones: Record<string, string> = {
    fresh: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    stale: "bg-rose-500/20 text-rose-300 border-rose-500/40",
    good: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
    warn: "bg-amber-500/20 text-amber-300 border-amber-500/40",
    neutral: "bg-slate-700/50 text-slate-300 border-slate-600/40",
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${tones[tone]}`}>{label}</span>
  );
}

export function PushPullCandleCard({ tick, title = "Latest candle cycle" }: { tick: TickData; title?: string }) {
  if (!tick) {
    return (
      <GlassPanel title={title}>
        <p className="text-sm text-slate-500">No scheduler tick completed yet.</p>
      </GlassPanel>
    );
  }

  const freshBars = Number(tick.fresh_bar_count ?? 0);
  const staleBars = Number(tick.stale_bar_count ?? 0);
  const freshQuotes = Number(tick.fresh_quote_count ?? 0);
  const approved = Number(tick.approved_count ?? 0);
  const orders = Number(tick.order_count ?? tick.orders_created ?? 0);
  const eligible = Number(tick.eligible_strategy_count ?? 0);

  let status = "Scanning";
  if (orders > 0) status = "Submitted";
  else if (approved > 0) status = "Entry approved";
  else if (Number(tick.push_signals_found ?? 0) > 0) status = "Push forming";
  else status = "Skipped";

  const rb = (tick.reason_breakdown as Record<string, number>) || {};

  return (
    <GlassPanel title={title}>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-sm font-semibold text-white">{status}</span>
        {pill(`Bars ${freshBars} fresh / ${staleBars} stale`, freshBars > 0 ? "fresh" : "stale")}
        {pill(`Quotes ${freshQuotes} fresh`, freshQuotes > 0 ? "fresh" : "neutral")}
        {pill(`${eligible} strategies`, eligible > 0 ? "good" : "warn")}
      </div>
      <p className="text-xs text-slate-300 leading-relaxed mb-3">{String(tick.plain ?? "")}</p>
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-1.5 mb-3">
        {STEPS.map((step, i) => {
          let state: "passed" | "blocked" | "skipped" = "skipped";
          if (step === "Scanned") state = "passed";
          if (step === "Push signal" && Number(tick.push_signals_found ?? 0) > 0) state = "passed";
          if (step === "Strategy check" && eligible > 0) state = "passed";
          if (step === "Paper submit" && orders > 0) state = "passed";
          if (step === "Paper submit" && approved > 0 && orders === 0) state = "blocked";
          if (step === "Quote refresh" && (rb.stale_quote_after_refresh || rb.stale_quote)) state = "blocked";
          const color =
            state === "passed"
              ? "border-emerald-500/50 text-emerald-300"
              : state === "blocked"
                ? "border-rose-500/50 text-rose-300"
                : "border-slate-700 text-slate-500";
          return (
            <div key={step} className={`text-[9px] text-center py-1 rounded border ${color}`}>
              {i + 1}. {step}
            </div>
          );
        })}
      </div>
      {Object.keys(rb).length > 0 && (
        <details className="text-[10px] text-slate-500">
          <summary className="cursor-pointer text-hive-cyan">Advanced — reason breakdown</summary>
          <pre className="mt-2 p-2 rounded bg-black/40 overflow-x-auto">{JSON.stringify(rb, null, 2)}</pre>
        </details>
      )}
    </GlassPanel>
  );
}

export function PaperOrderProofPanel({ proof }: { proof: Record<string, unknown> | null }) {
  if (!proof) return null;
  const counts = (proof.counts as Record<string, number>) || {};
  return (
    <GlassPanel title="Paper order proof">
      <p className="text-xs text-slate-300 mb-2">{String(proof.plain ?? "")}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[11px]">
        <div className="rounded-lg bg-black/30 p-2 border border-white/5">
          <div className="text-slate-500">Preflight blocked</div>
          <div className="text-white font-mono">{counts.preflight_blocked ?? 0}</div>
        </div>
        <div className="rounded-lg bg-black/30 p-2 border border-emerald-500/20">
          <div className="text-slate-500">Submitted to broker</div>
          <div className="text-emerald-300 font-mono">{counts.submitted_to_broker ?? 0}</div>
        </div>
        <div className="rounded-lg bg-black/30 p-2 border border-white/5">
          <div className="text-slate-500">Filled</div>
          <div className="text-white font-mono">{counts.filled ?? 0}</div>
        </div>
      </div>
      {(proof.latest_broker_order_id as string) && (
        <p className="text-[10px] text-cyan-300 mt-2 font-mono">
          Latest broker id: {String(proof.latest_broker_order_id)}
        </p>
      )}
      {(proof.latest_preflight_block as Record<string, unknown>)?.reject_reason && (
        <p className="text-[10px] text-amber-300 mt-1">
          Latest block: {String((proof.latest_preflight_block as Record<string, unknown>).reject_reason_plain || (proof.latest_preflight_block as Record<string, unknown>).reject_reason)}
        </p>
      )}
    </GlassPanel>
  );
}
