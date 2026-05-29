"use client";

import { useCallback, useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { TickerSymbol } from "@/components/ui/TickerSymbol";
import { apiGet } from "@/lib/apiClient";

type LogRow = {
  symbol?: string;
  side?: string;
  status?: string;
  broker_status?: string;
  quantity?: number;
  submitted_at?: string;
  stop_loss?: number;
  take_profit?: number;
  message?: string;
};

export function RecentPaperTradesPanel() {
  const [rows, setRows] = useState<LogRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const r = await apiGet<{ execution_logs?: LogRow[]; orders?: LogRow[] }>(
      "/api/execution/logs?scope=recent&limit=12",
      { timeoutMs: 8000 }
    );
    const list = r.data?.execution_logs ?? r.data?.orders ?? [];
    setRows(Array.isArray(list) ? list.slice(0, 12) : []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <GlassPanel title="Recent Paper Trades" icon={<Zap className="h-4 w-4 text-[#00FF66]" />}>
      <p className="text-[10px] text-slate-500 mb-2">Live execution log — TP/SL from dynamic exits</p>
      {loading ? (
        <p className="text-[10px] text-slate-500">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-[10px] text-amber-300/90">
          No paper orders yet. Enable paper learning and wait for scheduler ticks (~90s).
        </p>
      ) : (
        <ul className="space-y-1.5 max-h-[220px] overflow-y-auto">
          {rows.map((row, i) => (
            <li
              key={`${row.symbol}-${row.submitted_at}-${i}`}
              className="text-[10px] border border-white/5 rounded px-2 py-1.5 bg-white/[0.02]"
            >
              <div className="flex justify-between gap-2 items-center">
                <TickerSymbol symbol={String(row.symbol ?? "—")} size="sm" labelClassName="text-[10px] font-semibold text-white" />
                <span className="text-slate-400 text-[10px]">{row.side}</span>
                <span
                  className={
                    String(row.broker_status ?? row.status).includes("submit") ||
                    String(row.status).includes("filled")
                      ? "text-[#00FF66]"
                      : "text-amber-300"
                  }
                >
                  {row.broker_status ?? row.status}
                </span>
              </div>
              <p className="text-slate-500 mt-0.5">
                qty {row.quantity ?? "—"}
                {row.stop_loss != null && ` · SL ${Number(row.stop_loss).toFixed(4)}`}
                {row.take_profit != null && ` · TP ${Number(row.take_profit).toFixed(4)}`}
              </p>
              {row.submitted_at && (
                <p className="text-[9px] text-slate-600">{row.submitted_at.slice(0, 19)}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
