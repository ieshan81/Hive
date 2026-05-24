"""Reconcile Alpaca broker truth after order submit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, TradeRecord


def map_broker_status(broker_status: str) -> str:
    s = (broker_status or "").lower()
    if "partial" in s and "fill" in s:
        return "paper_order_partially_filled"
    if "filled" in s:
        return "paper_order_filled"
    if "canceled" in s or "cancelled" in s:
        return "paper_order_cancelled"
    if "rejected" in s or "expired" in s:
        return "paper_order_rejected"
    if "new" in s or "accepted" in s or "pending" in s:
        return "paper_order_submitted"
    return "paper_order_unfilled"


def reconcile_order(
    session: Session,
    *,
    execution_log: ExecutionLog,
    broker_order: dict[str, Any],
    alpaca,
    strategy: Optional[str] = None,
) -> dict[str, Any]:
    status = map_broker_status(broker_order.get("status", ""))
    filled_qty = broker_order.get("filled_qty") or 0
    filled_avg = broker_order.get("filled_avg_price")
    mid = execution_log.mid_at_decision

    shortfall = None
    if filled_avg and mid:
        side = (execution_log.side or "buy").lower()
        shortfall = (float(filled_avg) - float(mid)) if side == "buy" else (float(mid) - float(filled_avg))

    execution_log.status = status
    execution_log.filled_qty = float(filled_qty) if filled_qty else None
    execution_log.filled_avg_price = float(filled_avg) if filled_avg else None
    execution_log.accepted_at = datetime.utcnow()
    if broker_order.get("reject_reason"):
        execution_log.reject_reason = broker_order["reject_reason"]
    gates = dict(execution_log.gates_passed_json or {})
    gates["implementation_shortfall"] = shortfall
    execution_log.gates_passed_json = gates
    session.add(execution_log)

    order_row = session.exec(
        select(OrderRecord).where(OrderRecord.alpaca_order_id == execution_log.broker_order_id)
    ).first()
    if order_row:
        order_row.status = status.replace("paper_order_", "")
        order_row.filled_at = datetime.utcnow() if filled_qty else None
        order_row.filled_avg_price = filled_avg
        order_row.raw_payload = broker_order
        session.add(order_row)

    result: dict[str, Any] = {
        "status": status,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg,
        "implementation_shortfall": shortfall,
    }

    if filled_qty and float(filled_qty) > 0 and execution_log.signal_type == "entry":
        session.add(
            TradeRecord(
                symbol=execution_log.symbol,
                strategy=strategy or "crypto_push_pull",
                side="long",
                entry_price=float(filled_avg or execution_log.limit_price or 0),
                quantity=float(filled_qty),
                status="open",
                opened_at=datetime.utcnow(),
            )
        )
        result["trade_created"] = True

    alpaca.sync_account()
    alpaca.sync_positions()
    result["positions_synced"] = True

    if status in ("paper_order_filled", "paper_order_partially_filled"):
        try:
            from app.services.config_manager import ConfigManager
            from app.services.memory_triggers import on_paper_order_filled, on_qty_fee_difference
            from app.database import PositionSnapshot
            from sqlmodel import select

            config = ConfigManager(session).get_current()
            cid = execution_log.cycle_run_id or ""
            on_paper_order_filled(
                session, config, execution_log=execution_log, cycle_run_id=cid
            )
            filled = float(filled_qty or 0)
            if filled > 0:
                sym_norm = execution_log.symbol.upper().replace("/", "")
                rows = session.exec(select(PositionSnapshot)).all()
                broker_qty = max(
                    (float(p.qty) for p in rows if p.symbol.upper().replace("/", "") == sym_norm and (p.qty or 0) > 0),
                    default=0.0,
                )
                if broker_qty > 0:
                    on_qty_fee_difference(
                        session,
                        config,
                        filled_qty=filled,
                        broker_position_qty=broker_qty,
                        symbol=execution_log.symbol,
                        cycle_run_id=cid,
                        broker_order_id=execution_log.broker_order_id,
                        avg_entry_price=filled_avg,
                    )
        except Exception:
            pass

    return result


def reconciliation_status(session: Session, alpaca) -> dict[str, Any]:
    account = alpaca.sync_account()
    positions = alpaca.sync_positions()
    return {
        "account_synced": account is not None,
        "equity": account.equity if account else None,
        "positions_count": len([p for p in positions if (p.qty or 0) > 0]),
        "reconciled_at": datetime.utcnow().isoformat() + "Z",
    }
