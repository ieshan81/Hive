"use client";

import { enrichExecutionRow, enrichOrderRecord } from "@/lib/orderDisplay";
import { TickerSymbol } from "@/components/ui/TickerSymbol";

type Row = Record<string, unknown>;

function RowLine({
  row,
  mode,
  showAttribution,
}: {
  row: Row;
  mode: "execution" | "order";
  showAttribution?: boolean;
}) {
  const e = mode === "execution" ? enrichExecutionRow(row) : enrichOrderRecord(row);
  const rejected = Boolean(e.is_rejected);
  const historical = Boolean(row.historical);
  const symbol = String(e.symbol ?? "—");
  const side = String(e.side ?? "").toUpperCase();
  const statusLabel = String(e.status_label ?? e.status ?? "—");
  const typeLabel = String(e.order_type_label ?? "");
  const qty = String(e.requested_qty_display ?? e.qty_display ?? "—");
  const price = String(e.filled_avg_price_display ?? e.limit_price_display ?? "—");
  const reason = (row.reason as string) || (e.reject_reason_plain as string | null | undefined);
  const ts = String(row.timestamp ?? row.created_at ?? "—");
  const cycleId = String(row.cycle_run_id ?? "—");
  const tickId = String(row.scheduler_tick_id ?? "—");
  const sourceWindow = String(row.source_window ?? "—");
  const brokerStatus = String(row.broker_status ?? statusLabel);
  const outcome = String(row.outcome ?? statusLabel);

  return (
    <tr
      className={`border-t border-white/5 ${rejected ? "bg-red-950/20" : ""} ${historical ? "opacity-80" : ""}`}
      title={historical ? "Historical — not from latest scheduler tick" : undefined}
    >
      {showAttribution && (
        <>
          <td className="py-1.5 pr-2 text-slate-500 font-mono text-[9px] whitespace-nowrap">{ts}</td>
          <td className="py-1.5 pr-2 text-slate-500 font-mono text-[9px] max-w-[72px] truncate" title={cycleId}>
            {cycleId !== "—" ? cycleId.slice(0, 8) : "—"}
          </td>
          <td className="py-1.5 pr-2 text-slate-500 text-[9px]">{sourceWindow}</td>
          <td className="py-1.5 pr-2 text-slate-500 text-[9px]">{historical ? "yes" : "no"}</td>
        </>
      )}
      <td className="py-1.5 pr-2 text-slate-200">
        <span className="inline-flex items-center gap-2">
          <span className="uppercase text-[10px] text-slate-500">{side}</span>
          <TickerSymbol symbol={symbol} size="sm" labelClassName="text-[11px] text-slate-200" />
        </span>
      </td>
      <td className={`py-1.5 pr-2 ${rejected ? "text-red-400 font-medium" : "text-slate-300"}`}>{outcome}</td>
      <td className="py-1.5 pr-2 text-slate-400">{brokerStatus}</td>
      <td className="py-1.5 pr-2 text-slate-400">{typeLabel}</td>
      <td className="py-1.5 pr-2 text-slate-400">{qty}</td>
      <td className="py-1.5 pr-2 text-slate-400">{price}</td>
      <td className="py-1.5 text-slate-500 max-w-[200px]">
        {reason ?? (rejected ? "Rejected — not filled at broker." : "—")}
        {Boolean(e.looks_like_closed_position) ? (
          <span className="block text-[10px] text-amber-500/90 mt-0.5">Not a closed position — sell was rejected.</span>
        ) : null}
        {showAttribution && tickId !== "—" && (
          <span className="block text-[10px] text-slate-600 mt-0.5">tick: {tickId.slice(0, 19)}</span>
        )}
      </td>
    </tr>
  );
}

export function ExecutionOrdersTable({
  rows,
  mode = "execution",
  emptyMessage = "No execution logs for this view.",
  showAttribution = false,
}: {
  rows: Row[];
  mode?: "execution" | "order";
  emptyMessage?: string;
  showAttribution?: boolean;
}) {
  if (!rows.length) {
    return <p className="text-sm text-slate-500">{emptyMessage}</p>;
  }
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500 border-b border-white/5">
          {showAttribution && (
            <>
              <th className="text-left py-1 pr-2">Time</th>
              <th className="text-left py-1 pr-2">Cycle</th>
              <th className="text-left py-1 pr-2">Window</th>
              <th className="text-left py-1 pr-2">Hist.</th>
            </>
          )}
          <th className="text-left py-1 pr-2">Symbol</th>
          <th className="text-left py-1 pr-2">Outcome</th>
          <th className="text-left py-1 pr-2">Broker</th>
          <th className="text-left py-1 pr-2">Type</th>
          <th className="text-left py-1 pr-2">Qty</th>
          <th className="text-left py-1 pr-2">Price</th>
          <th className="text-left py-1">Reason</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <RowLine
            key={String(row.broker_order_id ?? row.event_id ?? row.client_order_id ?? i)}
            row={row}
            mode={mode}
            showAttribution={showAttribution}
          />
        ))}
      </tbody>
    </table>
  );
}
