"use client";

import { useCallback, useEffect, useState } from "react";
import { PieChart, RefreshCw } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { apiGet } from "@/lib/apiClient";

export function CapitalAllocatorPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [st, pl] = await Promise.all([
      apiGet<Record<string, unknown>>("/api/capital-allocator/status"),
      apiGet<Record<string, unknown>>("/api/capital-allocator/plan"),
    ]);
    if (st.ok) setStatus(st.data);
    else setError(st.error || `Status failed (${st.status})`);
    if (pl.ok) setPlan(pl.data);
    else if (!error) setError(pl.error || `Plan failed (${pl.status})`);
  }, [error]);

  useEffect(() => {
    load();
  }, [load]);

  const warnings = (plan?.degraded_warnings as string[]) || [];
  const div = (plan?.diversification_health as Record<string, unknown>) || {};
  const perSymbol = (plan?.per_symbol_budget as Record<string, unknown>[]) || [];
  const blocked = (plan?.blocked_symbols as { symbol?: string; reason?: string }[]) || [];

  return (
    <GlassPanel title="Capital Allocator" icon={<PieChart className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-500 mb-3">
        Learning capacity and exposure control — not arbitrary daily trade caps. Live trading stays locked.
      </p>

      {(plan?.status === "degraded" || status?.status === "degraded") && (
        <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-200">
          Degraded allocator: broker data stale or unavailable. No new execution from unknown buying power.
          {warnings.map((w) => (
            <div key={w} className="mt-1">
              {w}
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Market mode</div>
          <div className="font-semibold text-slate-200">{String(plan?.current_market_mode || status?.current_market_mode || "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Deployable capital</div>
          <div className="font-semibold">${String(plan?.deployable_capital ?? status?.deployable_capital ?? "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Stock hold budget</div>
          <div className="font-semibold">${String(plan?.stock_hold_budget ?? "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Crypto push-pull</div>
          <div className="font-semibold">${String(plan?.crypto_push_pull_budget ?? "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Overnight crypto reserve</div>
          <div className="font-semibold">${String(plan?.overnight_crypto_reserve ?? "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Cash safety reserve</div>
          <div className="font-semibold">${String(plan?.cash_reserve_budget ?? "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Stock exposure</div>
          <div className="font-semibold">${String(plan?.current_stock_exposure ?? "—")}</div>
        </div>
        <div className="rounded border border-white/10 p-2">
          <div className="text-slate-500">Crypto exposure</div>
          <div className="font-semibold">${String(plan?.current_crypto_exposure ?? "—")}</div>
        </div>
      </div>

      <div className="text-[9px] text-slate-500 mb-2">
        Diversification health: {div.healthy ? "Healthy" : "Watch"} · Broker freshness:{" "}
        {String(plan?.broker_data_freshness || status?.broker_data_freshness || "—")}
      </div>

      {perSymbol.length > 0 && (
        <div className="border-t border-white/5 pt-2 mb-2">
          <h3 className="text-[10px] font-semibold text-slate-400 mb-1">Per-symbol planned allocation</h3>
          <ul className="text-[9px] text-slate-400 max-h-20 overflow-y-auto space-y-0.5">
            {perSymbol.slice(0, 10).map((r) => (
              <li key={String(r.symbol)}>
                {String(r.symbol)}: ${String(r.approved_notional)} — {String(r.reason)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {blocked.length > 0 && (
        <div className="border-t border-white/5 pt-2">
          <h3 className="text-[10px] font-semibold text-slate-400 mb-1">Blocked symbols</h3>
          <ul className="text-[9px] text-amber-300/80 max-h-16 overflow-y-auto space-y-0.5">
            {blocked.slice(0, 8).map((b, i) => (
              <li key={`${b.symbol}-${i}`}>
                {b.symbol}: {b.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        className="mt-3 rounded border border-white/10 px-2 py-1 text-[10px]"
        onClick={() => load()}
      >
        <RefreshCw className="inline h-3 w-3 mr-1" />
        Refresh
      </button>
    </GlassPanel>
  );
}
