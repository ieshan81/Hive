"use client";

import { enrichExecutionRow, enrichOrderRecord } from "@/lib/orderDisplay";

type Row = Record<string, unknown>;

function RowLine({ row, mode }: { row: Row; mode: "execution" | "order" }) {
  const e = mode === "execution" ? enrichExecutionRow(row) : enrichOrderRecord(row);
  const rejected = Boolean(e.is_rejected);
  const symbol = String(e.symbol ?? "—");
  const side = String(e.side ?? "").toUpperCase();
  const statusLabel = String(e.status_label ?? e.status ?? "—");
  const typeLabel = String(e.order_type_label ?? "");
  const qty = String(e.requested_qty_display ?? e.qty_display ?? "—");
  const price = String(e.filled_avg_price_display ?? e.limit_price_display ?? "—");
  const reason = e.reject_reason_plain as string | null | undefined;

  return (
    <tr
      className={`border-t border-white/5 ${rejected ? "bg-red-950/20" : ""}`}
      title={rejected ? "Rejected — not a filled or closed position" : undefined}
    >
      <td className="py-1.5 pr-2 text-slate-200">
        {side} {symbol}
      </td>
      <td className={`py-1.5 pr-2 ${rejected ? "text-red-400 font-medium" : "text-slate-300"}`}>{statusLabel}</td>
      <td className="py-1.5 pr-2 text-slate-400">{typeLabel}</td>
      <td className="py-1.5 pr-2 text-slate-400">{qty}</td>
      <td className="py-1.5 pr-2 text-slate-400">{price}</td>
      <td className="py-1.5 text-slate-500 max-w-[200px]">
        {reason ?? (rejected ? "Rejected — not filled at broker." : "—")}
        {Boolean(e.looks_like_closed_position) ? (
          <span className="block text-[10px] text-amber-500/90 mt-0.5">Not a closed position — sell was rejected.</span>
        ) : null}
      </td>
    </tr>
  );
}

export function ExecutionOrdersTable({
  rows,
  mode = "execution",
  emptyMessage = "No execution logs for this view.",
}: {
  rows: Row[];
  mode?: "execution" | "order";
  emptyMessage?: string;
}) {
  if (!rows.length) {
    return <p className="text-sm text-slate-500">{emptyMessage}</p>;
  }
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500 border-b border-white/5">
          <th className="text-left py-1 pr-2">Symbol</th>
          <th className="text-left py-1 pr-2">Outcome</th>
          <th className="text-left py-1 pr-2">Type</th>
          <th className="text-left py-1 pr-2">Qty</th>
          <th className="text-left py-1 pr-2">Price</th>
          <th className="text-left py-1">Details</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <RowLine key={String(row.broker_order_id ?? row.event_id ?? row.client_order_id ?? i)} row={row} mode={mode} />
        ))}
      </tbody>
    </table>
  );
}
