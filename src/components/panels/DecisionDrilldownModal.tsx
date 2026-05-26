"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";
import {
  normalizeApproved,
  normalizeBlocked,
  normalizeDeferred,
  normalizeDecisionOrders,
  normalizeLessons,
} from "@/lib/apiNormalize";
import type { PanelLoadMeta } from "@/types/api";
import { PanelError } from "@/components/ui/PanelError";
import { ExecutionOrdersTable } from "@/components/ui/ExecutionOrdersTable";

export type DrillType = "approved" | "blocked" | "deferred" | "orders" | "lessons";

type OrderScope = "latest_tick" | "since_scheduler_enable" | "historical" | "cycle";

const TITLES: Record<DrillType, string> = {
  approved: "Approved decisions (latest cycle)",
  blocked: "Blocked decisions (latest cycle)",
  deferred: "Portfolio deferred (latest cycle)",
  orders: "Latest tick execution logs",
  lessons: "Lessons created (latest cycle)",
};

const ORDER_SCOPE_TITLES: Record<OrderScope, string> = {
  latest_tick: "Latest tick execution logs",
  since_scheduler_enable: "Execution logs since scheduler enabled",
  historical: "Historical execution logs",
  cycle: "Execution logs (portfolio latest cycle)",
};

const PATHS: Record<Exclude<DrillType, "orders">, string> = {
  approved: "/api/decisions/approved?cycle_run_id=latest",
  blocked: "/api/decisions/blocked?cycle_run_id=latest",
  deferred: "/api/decisions/deferred?cycle_run_id=latest",
  lessons: "/api/decisions/lessons?cycle_run_id=latest",
};

function ordersPath(scope: OrderScope): string {
  if (scope === "cycle") {
    return "/api/decisions/orders?scope=cycle&cycle_run_id=latest";
  }
  return `/api/decisions/orders?scope=${scope}`;
}

interface Props {
  type: DrillType | null;
  onClose: () => void;
}

export function DecisionDrilldownModal({ type, onClose }: Props) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [orderScope, setOrderScope] = useState<OrderScope>("latest_tick");
  const [emptyReason, setEmptyReason] = useState<string | null>(null);
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });

  useEffect(() => {
    if (!type) return;
    setLoading(true);
    const path = type === "orders" ? ordersPath(orderScope) : PATHS[type];
    apiGet(path).then((result) => {
      if (!result.ok || !result.data) {
        setRows([]);
        setEmptyReason(null);
        setMeta({
          source: "empty",
          lastUpdated: new Date().toISOString(),
          endpoint: path,
          httpStatus: result.status,
          error: result.error || `HTTP ${result.status}`,
        });
        setLoading(false);
        return;
      }
      let normalized: Record<string, unknown>[] = [];
      const data = result.data as Record<string, unknown>;
      switch (type) {
        case "approved":
          normalized = normalizeApproved(result.data) as Record<string, unknown>[];
          break;
        case "blocked":
          normalized = normalizeBlocked(result.data) as Record<string, unknown>[];
          break;
        case "deferred":
          normalized = normalizeDeferred(result.data) as Record<string, unknown>[];
          break;
        case "orders":
          normalized = normalizeDecisionOrders(result.data) as Record<string, unknown>[];
          setEmptyReason((data.empty_reason as string) || null);
          break;
        case "lessons":
          normalized = normalizeLessons(result.data) as Record<string, unknown>[];
          break;
      }
      setRows(normalized);
      setMeta({
        source: "live_api",
        lastUpdated: new Date().toISOString(),
        endpoint: path,
        httpStatus: result.status,
      });
      setLoading(false);
    });
  }, [type, orderScope]);

  if (!type) return null;

  const isOrders = type === "orders";
  const title = isOrders ? ORDER_SCOPE_TITLES[orderScope] : TITLES[type];

  const columns =
    !isOrders && rows.length > 0
      ? Object.keys(rows[0]).filter((k) => !k.startsWith("_")).slice(0, 8)
      : ["symbol", "status", "reason"];

  const emptyMessage =
    orderScope === "latest_tick"
      ? "No executions for the latest scheduler tick."
      : orderScope === "historical"
        ? "No historical execution logs in this window."
        : "No execution logs in this view.";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-3xl max-h-[80vh] bg-slate-900 border border-white/10 rounded-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex flex-col gap-2 px-4 py-3 border-b border-white/10">
          <div className="flex justify-between items-center">
            <h2 className="text-sm font-semibold text-white">{title}</h2>
            <button type="button" onClick={onClose} className="text-slate-400 hover:text-white text-xs">
              Close
            </button>
          </div>
          {isOrders && (
            <div className="flex flex-wrap gap-1">
              {(
                [
                  ["latest_tick", "Latest tick"],
                  ["since_scheduler_enable", "Since scheduler ON"],
                  ["historical", "Historical"],
                  ["cycle", "Portfolio cycle"],
                ] as const
              ).map(([scope, label]) => (
                <button
                  key={scope}
                  type="button"
                  onClick={() => setOrderScope(scope)}
                  className={`rounded px-2 py-0.5 text-[10px] border ${
                    orderScope === scope
                      ? "border-cyan-500/50 bg-cyan-500/20 text-cyan-100"
                      : "border-white/10 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </header>
        <div className="overflow-auto max-h-[calc(80vh-4.5rem)] p-4">
          {loading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : meta.error ? (
            <PanelError
              title="Decision drilldown failed"
              meta={meta}
              expectedShape="{ status: ok, orders|execution_logs: [...] }"
              receivedKeys={meta.endpoint ? undefined : []}
            />
          ) : rows.length === 0 ? (
            <p className="text-sm text-slate-500">
              {isOrders ? emptyMessage : "Endpoint succeeded with 0 rows for latest cycle."}
              {emptyReason === "no_scheduler_tick_yet" && (
                <span className="block text-[10px] mt-1 text-amber-400/90">
                  Scheduler is enabled but no tick has completed yet.
                </span>
              )}
              <span className="block font-mono text-[10px] mt-1 text-slate-600">{meta.endpoint}</span>
            </p>
          ) : isOrders ? (
            <ExecutionOrdersTable rows={rows} mode="execution" showAttribution />
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-white/5">
                  {columns.map((k) => (
                    <th key={k} className="text-left py-1 pr-2 font-medium">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-b border-white/5 text-slate-300">
                    {columns.map((k) => (
                      <td key={k} className="py-1.5 pr-2 align-top max-w-[160px] truncate">
                        {String(row[k] ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
