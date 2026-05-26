"use client";

import { useEffect, useState } from "react";
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

  useEffect(() => {
    setLoading(true);
    const path = `/api/decisions/orders?scope=${scope}`;
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
        <ExecutionOrdersTable rows={rows} mode="execution" showAttribution />
      )}
    </GlassPanel>
  );
}
