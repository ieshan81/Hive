"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type DrillType = "approved" | "blocked" | "deferred" | "orders" | "lessons";

const TITLES: Record<DrillType, string> = {
  approved: "Approved decisions (latest cycle)",
  blocked: "Blocked decisions (latest cycle)",
  deferred: "Portfolio deferred (latest cycle)",
  orders: "Execution logs (latest cycle)",
  lessons: "Lessons created (latest cycle)",
};

interface Props {
  type: DrillType | null;
  onClose: () => void;
}

export function DecisionDrilldownModal({ type, onClose }: Props) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!type) return;
    setLoading(true);
    const path =
      type === "orders"
        ? "orders"
        : type === "lessons"
          ? "lessons"
          : type;
    fetch(`${API_BASE}/api/decisions/${path}?cycle_run_id=latest`)
      .then((r) => r.json())
      .then((d) => {
        const key =
          type === "orders" ? "orders" : type === "lessons" ? "lessons" : "decisions";
        setRows(d[key] || []);
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [type]);

  if (!type) return null;

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
          ) : rows.length === 0 ? (
            <p className="text-sm text-slate-500">No rows for latest cycle.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-white/5">
                  {Object.keys(rows[0]).slice(0, 8).map((k) => (
                    <th key={k} className="text-left py-1 pr-2 font-medium">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-b border-white/5 text-slate-300">
                    {Object.keys(rows[0])
                      .slice(0, 8)
                      .map((k) => (
                        <td key={k} className="py-1.5 pr-2 align-top max-w-[140px] truncate">
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
