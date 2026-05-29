"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/apiClient";
import { normalizeDecisionOrders } from "@/lib/apiNormalize";
import { ExecutionOrdersTable } from "@/components/ui/ExecutionOrdersTable";
import { GlassPanel } from "@/components/ui/GlassPanel";

type OrderScope = "latest_tick" | "since_scheduler_enable" | "historical";

const LABELS: Record<OrderScope, string> = {
  latest_tick: "Latest tick",
  since_scheduler_enable: "Since scheduler ON",
  historical: "Historical",
};

export function PortfolioExecutionPanel() {
  const [scope, setScope] = useState<OrderScope>("latest_tick");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    setLoading(true);
    setShowDetails(false);
    const path = `/api/decisions/orders?scope=${scope}&limit=80`;
    apiGet(path).then((result) => {
      if (!result.ok || !result.data) {
        setRows([]);
        setEmptyReason(null);
        setLoading(false);
        return;
      }
      const data = result.data as Record<string, unknown>;
      const normalized = normalizeDecisionOrders(data) as Record<string, unknown>[];
      setRows(normalized);
      setEmptyReason((data.empty_reason as string) ?? null);
      setLoading(false);
    });
  }, [scope]);

  const blockerSummary = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) {
      const reason = String(row.reason ?? row.reject_reason_plain ?? row.reject_reason ?? row.status ?? "unknown");
      const key = reason.length > 80 ? `${reason.slice(0, 77)}...` : reason;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [rows]);

  const visibleRows = showDetails ? rows.slice(0, 80) : rows.slice(0, 25);

  return (
    <GlassPanel title="Execution logs">
      <div className="flex flex-wrap gap-1 mb-3">
        {(Object.keys(LABELS) as OrderScope[]).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setScope(s)}
            className={`text-[10px] px-2 py-1 rounded border ${
              scope === s ? "border-hive-cyan/40 text-hive-cyan bg-hive-cyan/10" : "border-white/10 text-slate-500"
            }`}
          >
            {LABELS[s]}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500">
          {emptyReason ??
            (scope === "latest_tick"
              ? "No executions for the latest tick."
              : "No execution logs in this scope.")}
        </p>
      ) : (
        <div className="space-y-3">
          <div className="rounded-md border border-white/10 bg-white/[0.02] p-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[11px] text-slate-400">
                Showing {visibleRows.length} of {rows.length} recent execution log rows.
              </p>
              {rows.length > 25 && (
                <button
                  type="button"
                  onClick={() => setShowDetails((v) => !v)}
                  className="rounded border border-white/10 px-2 py-1 text-[10px] text-slate-300 hover:bg-white/5"
                >
                  {showDetails ? "Show less" : "Show more"}
                </button>
              )}
            </div>
            {blockerSummary.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {blockerSummary.map(([reason, count]) => (
                  <span
                    key={reason}
                    className="rounded border border-amber-300/20 bg-amber-300/10 px-2 py-0.5 text-[10px] text-amber-200"
                  >
                    {reason}: {count}
                  </span>
                ))}
              </div>
            )}
          </div>
          <ExecutionOrdersTable rows={visibleRows} mode="execution" showAttribution />
        </div>
      )}
    </GlassPanel>
  );
}
