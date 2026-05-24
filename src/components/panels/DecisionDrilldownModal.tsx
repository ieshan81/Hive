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

export type DrillType = "approved" | "blocked" | "deferred" | "orders" | "lessons";

const TITLES: Record<DrillType, string> = {
  approved: "Approved decisions (latest cycle)",
  blocked: "Blocked decisions (latest cycle)",
  deferred: "Portfolio deferred (latest cycle)",
  orders: "Execution logs (latest cycle)",
  lessons: "Lessons created (latest cycle)",
};

const PATHS: Record<DrillType, string> = {
  approved: "/api/decisions/approved?cycle_run_id=latest",
  blocked: "/api/decisions/blocked?cycle_run_id=latest",
  deferred: "/api/decisions/deferred?cycle_run_id=latest",
  orders: "/api/decisions/orders?cycle_run_id=latest",
  lessons: "/api/decisions/lessons?cycle_run_id=latest",
};

interface Props {
  type: DrillType | null;
  onClose: () => void;
}

export function DecisionDrilldownModal({ type, onClose }: Props) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<PanelLoadMeta>({ source: "empty", lastUpdated: new Date().toISOString() });

  useEffect(() => {
    if (!type) return;
    setLoading(true);
    const path = PATHS[type];
    apiGet(path).then((result) => {
      if (!result.ok || !result.data) {
        setRows([]);
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
  }, [type]);

  if (!type) return null;

  const columns =
    rows.length > 0
      ? Object.keys(rows[0]).filter((k) => !k.startsWith("_")).slice(0, 8)
      : ["symbol", "status", "reason"];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[80vh] bg-slate-900 border border-white/10 rounded-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex justify-between items-center px-4 py-3 border-b border-white/10">
          <h2 className="text-sm font-semibold text-white">{TITLES[type]}</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white text-xs">
            Close
          </button>
        </header>
        <div className="overflow-auto max-h-[calc(80vh-3rem)] p-4">
          {loading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : meta.error ? (
            <PanelError
              title="Decision drilldown failed"
              meta={meta}
              expectedShape="{ status: ok, decisions|blocked|approved: [...] }"
              receivedKeys={meta.endpoint ? undefined : []}
            />
          ) : rows.length === 0 ? (
            <p className="text-sm text-slate-500">
              Endpoint succeeded with 0 rows for latest cycle.
              <span className="block font-mono text-[10px] mt-1 text-slate-600">{meta.endpoint}</span>
            </p>
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
