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
            return "Blocked before broker — order was not sent to Alpaca."
        if status == "paper_order_rejected":
            return "Broker rejected this order after it was submitted."
        return None
    r = str(reason).strip()
    low = r.lower()
    if r == "STALE_QUOTE" or "stale_quote" in low:
        return (
            "Price quote was too old at submit time. Bot refreshed the quote; "
            "if still stale, it skipped instead of sending a bad order."
        )
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


def _broker_detail_from_gates(gates_failed: dict) -> dict[str, Any]:
    if not isinstance(gates_failed, dict):
        return {}
    body = gates_failed.get("broker_error_body") or gates_failed.get("response_body")
    if body is None and gates_failed.get("broker"):
        import json

        raw = gates_failed.get("broker")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"raw": raw}
        elif isinstance(raw, dict):
            body = raw
    return {
        "http_status": gates_failed.get("http_status"),
        "alpaca_code": gates_failed.get("alpaca_code"),
        "alpaca_message": gates_failed.get("alpaca_message") or gates_failed.get("broker_message"),
        "broker_error_body": body,
        "request_payload": gates_failed.get("request_payload"),
        "submitted_to_broker": gates_failed.get("submitted_to_broker"),
        "broker_response_received": gates_failed.get("broker_response_received"),
        "blocked_before_broker": gates_failed.get("blocked_before_broker"),
    }


def enrich_execution_row(row: dict[str, Any]) -> dict[str, Any]:
    status = row.get("status")
    broker_id = row.get("broker_order_id") or row.get("brokerOrderId")
    side = row.get("side") or ""
    gates_failed = row.get("gates_failed_json") or row.get("gates_failed") or {}
    broker_detail = _broker_detail_from_gates(gates_failed) if isinstance(gates_failed, dict) else {}
    if isinstance(gates_failed, dict) and gates_failed.get("outcome_bucket"):
        bucket = gates_failed.get("outcome_bucket")
    else:
        bucket = order_outcome_bucket(status, has_broker_id=bool(broker_id))
    rejected = is_rejected_display(status)
    broker_reject_after_submit = status == "paper_order_rejected" and (
        gates_failed.get("preflight_stage") == "broker_rejection"
        if isinstance(gates_failed, dict)
        else False
    )
    preflight = status in PREFLIGHT_STATUSES or (
        not broker_id
        and not broker_reject_after_submit
        and status in ("preflight_blocked", "paper_order_pending")
    )
    submitted = bool(broker_id) or broker_reject_after_submit or (
        isinstance(gates_failed, dict) and gates_failed.get("submitted_to_broker") is True
    )
    display_status = (
        "Blocked before broker"
        if preflight and not submitted
        else (
            "Broker rejected after submit"
            if broker_reject_after_submit
            else order_status_label(status)
        )
    )
    plain_reason = reject_reason_plain(row.get("reject_reason") or row.get("rejectReason"), status=status)
    if broker_reject_after_submit and broker_detail.get("alpaca_message"):
        plain_reason = str(broker_detail["alpaca_message"])
    return {
        **row,
        "status_label": display_status,
        "blocked_before_broker": preflight and not submitted,
        "submitted_to_broker": submitted,
        "broker_response_received": broker_detail.get("broker_response_received")
        if broker_detail
        else bool(broker_reject_after_submit),
        "broker_rejection": broker_detail if broker_detail else None,
        "alpaca_message": broker_detail.get("alpaca_message"),
        "order_type_label": order_type_label(row.get("order_type") or row.get("orderType")),
        "limit_price_display": format_decimal(row.get("limit_price") or row.get("limitPrice")),
        "filled_avg_price_display": format_decimal(row.get("filled_avg_price") or row.get("filledAvgPrice")),
        "requested_qty_display": format_decimal(row.get("requested_qty") or row.get("qty")),
        "reject_reason_plain": plain_reason,
        "outcome_bucket": bucket,
        "is_rejected": rejected,
        "is_filled": (status or "") in FILLED_STATUSES,
        "looks_like_closed_position": rejected and str(side).lower() == "sell",
        "user_message": (
            f"{str(side).upper()} {row.get('symbol', '?')}: {display_status}"
            + (f" — {plain_reason}" if rejected and plain_reason else "")
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
