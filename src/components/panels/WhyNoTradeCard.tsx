"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

export function WhyNoTradeCard() {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);

  const load = useCallback(async () => {
    const [cockpit, shortlist] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/cockpit", { timeoutMs: 90000 }),
      apiGet<Record<string, unknown>>("/api/universe/execution-shortlist"),
    ]);
    const c = cockpit.data || {};
    const ctrl = (c.control as Record<string, unknown>) || {};
    const scores = (c.scores as Record<string, unknown>[]) || [];
    const top = scores[0];
    setPayload({
      execution_shortlist_count: shortlist.data?.execution_shortlist_count ?? (c.funnel as Record<string, number>)?.shortlist ?? 0,
      eligible_count: shortlist.data?.eligible_count ?? c.passed_count ?? 0,
      funnel_answer: c.why_zero_shortlist || c.ai_cockpit_message,
      strategy_verdict: ctrl.bot_can_place ? "ready" : "blocked",
      should_paper_trade_now: Boolean(ctrl.can_place_paper_orders && ctrl.paper_learning_on),
      open_positions: c.positions,
      last_tick_reason: Array.isArray(ctrl.blockers) ? ctrl.blockers.join(", ") : c.ai_cockpit_message,
      top_candidate: top ? { symbol: top.symbol, trade_quality_score: top.quality_score } : undefined,
      next_experiment: null,
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
