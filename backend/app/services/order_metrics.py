"""Normalized order count definitions for dashboard and APIs."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord


def order_summary(session: Session) -> dict[str, Any]:
    orders = session.exec(select(OrderRecord)).all()
    logs = session.exec(select(ExecutionLog)).all()

    attempted = len(logs) + len([o for o in orders if o.status not in ("draft",)])
    sent = len([o for o in orders if o.alpaca_order_id])
    filled = len([o for o in orders if o.status == "filled"])
    rejected_logs = [
        l
        for l in logs
        if l.status in ("paper_order_rejected", "preflight_blocked", "broker_rejected")
        or (l.reject_reason and "REJECT" in str(l.reject_reason).upper())
    ]
    rejected_orders = [o for o in orders if "reject" in (o.status or "").lower()]
    rejected = len({l.id for l in rejected_logs}) + len(rejected_orders)
    blocked_preflight = len([l for l in logs if l.status == "preflight_blocked"])

    last_msg = "No orders yet."
    if rejected_logs:
        last = rejected_logs[-1]
        if last.status == "preflight_blocked":
            last_msg = "Last order attempt was blocked by safety check before broker."
        else:
            last_msg = "Last order attempt was rejected — not filled at broker."

    return {
        "orders_attempted": attempted,
        "orders_sent_to_broker": sent,
        "orders_filled": filled,
        "orders_rejected": max(rejected, len(rejected_logs)),
        "orders_blocked_preflight": blocked_preflight,
        "orders_total_records": len(orders),
        "last_order_user_message": last_msg,
    }
