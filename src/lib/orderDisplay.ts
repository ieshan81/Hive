/** Plain-language order / execution log display (mirrors backend order_display.py). */

export type OrderOutcomeBucket =
  | "attempted"
  | "sent"
  | "filled"
  | "rejected"
  | "preflight_blocked";

const ORDER_STATUS_LABELS: Record<string, string> = {
  paper_order_filled: "Filled at broker",
  paper_order_rejected: "Paper order rejected",
  paper_order_cancelled: "Cancelled",
  paper_order_unfilled: "Not filled",
  preflight_blocked: "Blocked by safety check before broker",
  broker_rejected: "Broker rejected",
  pending: "Pending",
  submitted: "Sent to broker",
  filled: "Filled",
};

const ORDER_TYPE_LABELS: Record<string, string> = {
  marketable_limit_ioc: "Instant market-price limit order",
  limit: "Limit order",
  market: "Market order",
};

const REJECTED = new Set([
  "paper_order_rejected",
  "preflight_blocked",
  "broker_rejected",
  "paper_order_cancelled",
  "paper_order_unfilled",
]);

export function formatDecimal(value: unknown, maxPlaces = 8): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  if (n === 0) return "0";
  let text = n.toFixed(maxPlaces).replace(/\.?0+$/, "");
  const dot = text.indexOf(".");
  if (dot >= 0) {
    const whole = text.slice(0, dot);
    let frac = text.slice(dot + 1);
    if (frac.length > 6) frac = frac.slice(0, 6).replace(/0+$/, "");
    text = frac ? `${whole}.${frac}` : whole;
  }
  return text;
}

export function orderStatusLabel(status: string | null | undefined): string {
  if (!status) return "Unknown";
  return ORDER_STATUS_LABELS[status] ?? status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function orderTypeLabel(orderType: string | null | undefined): string {
  if (!orderType) return "—";
  return ORDER_TYPE_LABELS[orderType] ?? orderType.replace(/_/g, " ");
}

export function rejectReasonPlain(
  reason: string | null | undefined,
  status?: string | null
): string | null {
  if (!reason) {
    if (status === "preflight_blocked") return "Blocked by safety check before broker.";
    if (status === "paper_order_rejected") return "Broker or paper cage rejected this order — not filled.";
    return null;
  }
  const r = String(reason).trim();
  const low = r.toLowerCase();
  if (low.includes("min_notional") || low.includes("notional")) {
    return "Order size was below the broker minimum — rejected, not filled.";
  }
  if (low.includes("insufficient")) {
    return "Insufficient buying power or quantity — rejected, not filled.";
  }
  if (low.includes("available") && low.includes("qty")) {
    return "Broker reported zero available quantity to sell — rejected, not filled.";
  }
  return r.length > 120 ? `${r.slice(0, 117)}…` : r;
}

export function orderOutcomeBucket(
  status: string | null | undefined,
  hasBrokerId?: boolean
): OrderOutcomeBucket {
  if (!status) return "attempted";
  if (status === "preflight_blocked") return "preflight_blocked";
  if (REJECTED.has(status)) return "rejected";
  if (status === "paper_order_filled" || status === "filled") return "filled";
  if (hasBrokerId || status === "submitted" || status === "pending") return "sent";
  return "attempted";
}

export function isRejectedStatus(status: string | null | undefined): boolean {
  return !!status && (REJECTED.has(status) || status.toLowerCase().includes("reject"));
}

export function enrichExecutionRow(row: Record<string, unknown>): Record<string, unknown> {
  const status = String(row.status ?? "");
  const brokerId = row.broker_order_id ?? row.brokerOrderId;
  const side = String(row.side ?? "");
  const rejected = isRejectedStatus(status);
  const bucket = orderOutcomeBucket(status, !!brokerId);
  const reason = (row.reject_reason ?? row.rejectReason) as string | undefined;
  return {
    ...row,
    status_label: orderStatusLabel(status),
    order_type_label: orderTypeLabel(String(row.order_type ?? row.orderType ?? "marketable_limit_ioc")),
    limit_price_display: formatDecimal(row.limit_price ?? row.limitPrice),
    filled_avg_price_display: formatDecimal(row.filled_avg_price ?? row.filledAvgPrice),
    requested_qty_display: formatDecimal(row.requested_qty ?? row.qty),
    reject_reason_plain: rejectReasonPlain(reason, status),
    outcome_bucket: bucket,
    is_rejected: rejected,
    looks_like_closed_position: rejected && side.toLowerCase() === "sell",
  };
}

export function enrichOrderRecord(row: Record<string, unknown>): Record<string, unknown> {
  const status = String(row.status ?? "");
  const brokerId = row.broker_order_id ?? row.brokerOrderId ?? row.alpaca_order_id;
  const rejected = isRejectedStatus(status) || status.toLowerCase().includes("reject");
  const filled = status.toLowerCase() === "filled";
  const side = String(row.side ?? "");
  return {
    ...row,
    status_label: filled ? "Filled" : rejected ? "Rejected" : orderStatusLabel(status),
    order_type_label: orderTypeLabel(String(row.order_type ?? row.orderType ?? "")),
    qty_display: formatDecimal(row.qty),
    filled_avg_price_display: formatDecimal(row.filled_avg_price ?? row.filledAvgPrice),
    outcome_bucket: orderOutcomeBucket(status, !!brokerId),
    is_rejected: rejected,
    looks_like_closed_position: rejected && side.toLowerCase() === "sell",
  };
}

export interface OrderSummaryCounts {
  orders_attempted?: number;
  orders_sent_to_broker?: number;
  orders_filled?: number;
  orders_rejected?: number;
  orders_blocked_preflight?: number;
  last_order_user_message?: string;
}
