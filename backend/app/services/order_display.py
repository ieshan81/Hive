"""Plain-language order and execution log labels for APIs and UI."""

from __future__ import annotations

from typing import Any

ORDER_STATUS_LABELS: dict[str, str] = {
    "paper_order_filled": "Filled at broker",
    "paper_order_rejected": "Paper order rejected",
    "paper_order_cancelled": "Cancelled",
    "paper_order_unfilled": "Not filled",
    "preflight_blocked": "Blocked by safety check before broker",
    "broker_rejected": "Broker rejected",
    "pending": "Pending",
    "submitted": "Sent to broker",
}

ORDER_TYPE_LABELS: dict[str, str] = {
    "marketable_limit_ioc": "Instant market-price limit order",
    "limit": "Limit order",
    "market": "Market order",
}

REJECTED_STATUSES = frozenset(
    {"paper_order_rejected", "preflight_blocked", "broker_rejected", "paper_order_cancelled", "paper_order_unfilled"}
)
FILLED_STATUSES = frozenset({"paper_order_filled", "filled"})
PREFLIGHT_STATUSES = frozenset({"preflight_blocked"})


def format_decimal(value: float | int | None, *, max_places: int = 8) -> str | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if n == 0:
        return "0"
    text = f"{n:.{max_places}f}".rstrip("0").rstrip(".")
    if "." in text:
        whole, frac = text.split(".", 1)
        if len(frac) > 6:
            frac = frac[:6].rstrip("0")
        text = f"{whole}.{frac}" if frac else whole
    return text


def order_status_label(status: str | None) -> str:
    if not status:
        return "Unknown"
    return ORDER_STATUS_LABELS.get(status, status.replace("_", " ").capitalize())


def order_type_label(order_type: str | None) -> str:
    if not order_type:
        return "—"
    return ORDER_TYPE_LABELS.get(order_type, order_type.replace("_", " ").capitalize())


def reject_reason_plain(reason: str | None, *, status: str | None = None) -> str | None:
    if not reason:
        if status in PREFLIGHT_STATUSES:
            return "Blocked by safety check before broker."
        if status == "paper_order_rejected":
            return "Broker or paper cage rejected this order — not filled."
        return None
    r = str(reason).strip()
    low = r.lower()
    if "min_notional" in low or "notional" in low:
        return "Order size was below the broker minimum — rejected, not filled."
    if "insufficient" in low:
        return "Insufficient buying power or quantity — rejected, not filled."
    if "available" in low and "qty" in low:
        return "Broker reported zero available quantity to sell — rejected, not filled."
    if len(r) > 120:
        return r[:117] + "…"
    return r


def order_outcome_bucket(status: str | None, *, has_broker_id: bool = False) -> str:
    if not status:
        return "attempted"
    if status in PREFLIGHT_STATUSES:
        return "preflight_blocked"
    if status in REJECTED_STATUSES:
        return "rejected"
    if status in FILLED_STATUSES:
        return "filled"
    if has_broker_id or status in ("submitted", "pending"):
        return "sent"
    return "attempted"


def is_rejected_display(status: str | None) -> bool:
    return (status or "") in REJECTED_STATUSES


def enrich_execution_row(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("status")
    broker_id = row.get("broker_order_id") or row.get("brokerOrderId")
    side = row.get("side") or ""
    bucket = order_outcome_bucket(status, has_broker_id=bool(broker_id))
    rejected = is_rejected_display(status)
    return {
        **row,
        "status_label": order_status_label(status),
        "order_type_label": order_type_label(row.get("order_type") or row.get("orderType")),
        "limit_price_display": format_decimal(row.get("limit_price") or row.get("limitPrice")),
        "filled_avg_price_display": format_decimal(row.get("filled_avg_price") or row.get("filledAvgPrice")),
        "requested_qty_display": format_decimal(row.get("requested_qty") or row.get("qty")),
        "reject_reason_plain": reject_reason_plain(row.get("reject_reason") or row.get("rejectReason"), status=status),
        "outcome_bucket": bucket,
        "is_rejected": rejected,
        "is_filled": (status or "") in FILLED_STATUSES,
        "looks_like_closed_position": rejected and str(side).lower() == "sell",
        "user_message": (
            f"{str(side).upper()} {row.get('symbol', '?')}: {order_status_label(status)}"
            + (f" — {reject_reason_plain(row.get('reject_reason') or row.get('rejectReason'), status=status)}" if rejected else "")
        ),
    }


def enrich_order_record(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("status")
    broker_id = row.get("broker_order_id") or row.get("brokerOrderId") or row.get("alpaca_order_id")
    bucket = order_outcome_bucket(status, has_broker_id=bool(broker_id))
    rejected = is_rejected_display(status) or "reject" in str(status or "").lower()
    filled = str(status or "").lower() == "filled"
    return {
        **row,
        "status_label": order_status_label(status) if status in ORDER_STATUS_LABELS else (
            "Filled" if filled else ("Rejected" if rejected else str(status or "Unknown").replace("_", " ").capitalize())
        ),
        "order_type_label": order_type_label(row.get("order_type") or row.get("orderType")),
        "qty_display": format_decimal(row.get("qty")),
        "filled_avg_price_display": format_decimal(row.get("filled_avg_price") or row.get("filledAvgPrice")),
        "outcome_bucket": bucket,
        "is_rejected": rejected,
        "is_filled": filled,
        "looks_like_closed_position": rejected and str(row.get("side", "")).lower() == "sell",
    }
