"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

export function WhyNoTradeCard() {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);

  const load = useCallback(async () => {
    const [mc, verdict, shortlist] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/mission-control/status"),
      apiGet<Record<string, unknown>>("/api/strategy/push-pull/verdict"),
      apiGet<Record<string, unknown>>("/api/universe/execution-shortlist"),
    ]);
    const tick = ((mc.data?.push_pull_engine as Record<string, unknown>)?.last_tick || {}) as Record<
      string,
      unknown
    >;
    setPayload({
      execution_shortlist_count: shortlist.data?.execution_shortlist_count ?? 0,
      eligible_count: shortlist.data?.eligible_count ?? 0,
      funnel_answer: shortlist.data?.answer || verdict.data?.funnel_answer,
      strategy_verdict: verdict.data?.current_status,
      should_paper_trade_now: verdict.data?.should_paper_trade_now,
      open_positions: mc.data?.account_survival,
      last_tick_reason: tick.result || tick.no_trade_reason,
      top_candidate: tick.top_candidate,
      next_experiment: verdict.data?.next_experiment,
    });
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 45000);
    return () => clearInterval(t);
  }, [load]);

  const top = payload?.top_candidate as Record<string, unknown> | undefined;
  const survival = payload?.open_positions as Record<string, unknown> | undefined;

  return (
    <GlassPanel title="Why no quick paper trade?" icon={<ShieldAlert className="h-4 w-4 text-amber-400" />}>
      <ul className="text-[11px] text-slate-400 space-y-1.5">
        <li>
          Execution shortlist: <span className="text-white">{String(payload?.execution_shortlist_count ?? "—")}</span>
        </li>
        <li>
          Strategy verdict:{" "}
          <span className="text-amber-300 capitalize">{String(payload?.strategy_verdict ?? "—")}</span>
        </li>
        <li>
          Paper trade now: {payload?.should_paper_trade_now ? "yes" : "no"}
        </li>
        <li>Last tick: {String(payload?.last_tick_reason ?? "—").replace(/_/g, " ")}</li>
        {top?.symbol ? (
          <li>
            Top scored: {String(top.symbol)} (quality {String(top.trade_quality_score ?? "—")})
          </li>
        ) : null}
        {survival && Number(survival.open_positions_value ?? 0) > 0 ? (
          <li>Open broker exposure — duplicate-entry protection may block new entries.</li>
        ) : null}
      </ul>
      {payload?.funnel_answer ? (
        <p className="text-[10px] text-slate-500 mt-3 border-t border-white/5 pt-2">
          {String(payload.funnel_answer).slice(0, 320)}
        </p>
      ) : null}
      {payload?.next_experiment ? (
        <p className="text-[10px] text-hive-cyan mt-2">
          Research next: {String(payload.next_experiment)}
        </p>
      ) : null}
    </GlassPanel>
  );
}
