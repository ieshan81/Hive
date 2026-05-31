"use client";

import { useCallback, useEffect, useState } from "react";
import { Wallet, RefreshCw, AlertTriangle, Info } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiGet, apiPostOperator } from "@/lib/apiClient";
import { PortfolioExecutionPanel } from "@/components/panels/PortfolioExecutionPanel";
import { PortfolioLineChart } from "@/components/panels/PortfolioLineChart";
import { PortfolioOrdersLedger } from "@/components/ui/PortfolioOrdersLedger";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { formatDisplaySymbol } from "@/lib/assetIcons";

type BrokerRow = {
  symbol?: string;
  qty?: number;
  avg_entry?: number;
  current_price?: number;
  market_value?: number;
  unrealized_pl?: number;
  unrealized_pl_pct?: number;
  local_history_incomplete?: boolean;
  local_history_note?: string;
};

type ExitPlan = {
  symbol?: string;
  has_exit_plan?: boolean;
  missing_exit_plan?: boolean;
  exit_plan_source?: string;
  stop_loss?: number | null;
  take_profit?: number | null;
};

function planKey(symbol: string): string {
  return String(symbol || "").toUpperCase().replace(/[/-]/g, "");
}

export default function PortfolioPage() {
  const [recon, setRecon] = useState<Record<string, unknown> | null>(null);
  const [exitStatus, setExitStatus] = useState<Record<string, string>>({});
  const [exitPlans, setExitPlans] = useState<Record<string, ExitPlan>>({});
  const [armedExitSymbol, setArmedExitSymbol] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [reconRes, exitRes] = await Promise.all([
      apiGet("/api/portfolio/reconciliation"),
      apiGet<Record<string, unknown>>("/api/push-pull/exit-monitor/status", { timeoutMs: 5000 }),
    ]);

    if (reconRes.ok) setRecon(reconRes.data as Record<string, unknown>);
    else setRecon(null);

    if (exitRes.ok && exitRes.data) {
      const plans = (exitRes.data.positions as ExitPlan[]) || [];
      const map: Record<string, ExitPlan> = {};
      for (const p of plans) map[planKey(String(p.symbol ?? ""))] = p;
      setExitPlans(map);
    } else {
      setExitPlans({});
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    await apiPostOperator("/api/positions/refresh", { actor: "portfolio_ui" });
    await load();
  }

  async function requestPaperSell(symbol: string) {
    if (armedExitSymbol !== symbol) {
      setArmedExitSymbol(symbol);
      setExitStatus((s) => ({
        ...s,
        [symbol]: "Click Confirm Paper Sell to submit through the paper preflight.",
      }));
      return;
    }
    setArmedExitSymbol(null);
    setExitStatus((s) => ({ ...s, [symbol]: "Submitting caged paper sell..." }));
    const routeSymbol = symbol.replace("/", "");
    const res = await apiPostOperator(`/api/positions/${encodeURIComponent(routeSymbol)}/manual-exit-request`, {
      actor: "portfolio_ui",
    });
    const status = res.ok
      ? `Result: ${String((res.data as Record<string, unknown> | null)?.status ?? "submitted")}`
      : `Blocked: ${res.error || `HTTP ${res.status}`}`;
    setExitStatus((s) => ({ ...s, [symbol]: status }));
    await load();
  }

  const brokerTruth = (recon?.broker_truth as Record<string, unknown>) || {};
  const brokerRows = (brokerTruth.positions as BrokerRow[]) || [];
  const positionSymbols = brokerRows.map((p) => formatDisplaySymbol(String(p.symbol ?? "")));
  const warning = recon?.reconciliation_warning as string | undefined;
  const isInfoNote = Boolean(brokerRows.some((p) => p.local_history_note));

  return (
    <section className="max-w-5xl space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet className="h-6 w-6 text-hive-cyan" />
          <h1 className="text-xl font-semibold text-white">Portfolio</h1>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="flex items-center gap-1 text-xs text-hive-cyan border border-hive-cyan/30 rounded px-3 py-1.5"
        >
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </header>

      {loading ? (
        <EmptyState message="Loading broker positions…" />
      ) : (
        <>
          {warning && (
            <div
              className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${
                isInfoNote && !brokerRows.some((p) => p.local_history_incomplete)
                  ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-100"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-200"
              }`}
            >
              {isInfoNote && !brokerRows.some((p) => p.local_history_incomplete) ? (
                <Info className="h-4 w-4 shrink-0 mt-0.5" />
              ) : (
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              )}
              <p>{warning}</p>
            </div>
          )}

          {positionSymbols.length > 0 && (
            <PortfolioLineChart symbols={positionSymbols} defaultSymbol={positionSymbols[0]} />
          )}

          <GlassPanel title="Open positions">
            {brokerRows.length === 0 ? (
              <EmptyState message="No open broker positions." />
            ) : (
              <ul className="space-y-3">
                {brokerRows.map((pos) => {
                  const sym = formatDisplaySymbol(String(pos.symbol));
                  const plan = exitPlans[planKey(String(pos.symbol ?? ""))];
                  const planMissing = plan ? Boolean(plan.missing_exit_plan) : undefined;
                  return (
                    <li
                      key={sym}
                      className="rounded-lg border border-white/5 bg-white/[0.02] p-3 flex flex-wrap items-center justify-between gap-3"
                    >
                      <div>
                        <TickerSymbol symbol={sym} size="sm" labelClassName="font-semibold text-white" />
                        <p className="text-[10px] text-slate-500 mt-1">
                          Qty {String(pos.qty)} · entry {String(pos.avg_entry ?? "—")} · mark{" "}
                          {String(pos.current_price ?? "—")} · P/L{" "}
                          <span className={(pos.unrealized_pl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}>
                            {String(pos.unrealized_pl ?? "—")}
                            {pos.unrealized_pl_pct != null ? ` (${pos.unrealized_pl_pct}%)` : ""}
                          </span>
                        </p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                          {planMissing === undefined ? (
                            <span className="rounded-full border border-white/10 px-2 py-0.5 text-slate-500">
                              exit plan: unknown
                            </span>
                          ) : planMissing ? (
                            <span className="rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 font-semibold text-rose-300">
                              missing exit plan — blocks new entries
                            </span>
                          ) : (
                            <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-semibold text-emerald-300">
                              exit plan: {plan?.exit_plan_source || "ok"}
                            </span>
                          )}
                          {plan && (plan.stop_loss != null || plan.take_profit != null) && (
                            <span className="text-slate-500">
                              {plan.stop_loss != null ? `stop ${plan.stop_loss}` : ""}
                              {plan.stop_loss != null && plan.take_profit != null ? " · " : ""}
                              {plan.take_profit != null ? `target ${plan.take_profit}` : ""}
                            </span>
                          )}
                        </div>
                        {pos.local_history_note && (
                          <p className="text-[10px] text-cyan-300/80 mt-1">{pos.local_history_note}</p>
                        )}
                        {exitStatus[sym] && (
                          <p className="text-[11px] text-amber-200 mt-1">{exitStatus[sym]}</p>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => requestPaperSell(sym)}
                        className={
                          armedExitSymbol === sym
                            ? "rounded border border-amber-300/60 bg-amber-400/15 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-100"
                            : "rounded border border-rose-400/40 bg-rose-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-rose-200"
                        }
                      >
                        {armedExitSymbol === sym ? "Confirm paper sell" : "Paper sell"}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </GlassPanel>

          <GlassPanel title="Order & Trade Ledger">
            <PortfolioOrdersLedger />
          </GlassPanel>

          <PortfolioExecutionPanel />
        </>
      )}
    </section>
  );
}
