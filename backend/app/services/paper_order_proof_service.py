"""Paper order proof — operator-visible submit vs preflight vs broker outcomes."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import get_latest_reset_epoch, record_created_after
from app.services.order_display import enrich_execution_row, enrich_order_record


class PaperOrderProofService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def summary(self) -> dict[str, Any]:
        epoch = get_latest_reset_epoch(self.session)
        cutoff = epoch.get("nuke_completed_at") if epoch else None

        logs = list(
            self.session.exec(select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(200)).all()
        )
        if cutoff:
            logs = [l for l in logs if record_created_after(l, cutoff)]

        preflight_blocked = []
        submitted = []
        broker_rejected = []
        filled = []

        for log in logs:
            row = enrich_execution_row(
                {
                    "symbol": log.symbol,
                    "side": log.side,
                    "status": log.status,
                    "reject_reason": log.reject_reason,
                    "broker_order_id": log.broker_order_id,
                    "broker_client_order_id": log.broker_client_order_id,
                    "limit_price": log.limit_price,
                    "requested_qty": log.requested_qty,
                    "requested_notional": log.requested_notional,
                    "filled_avg_price": log.filled_avg_price,
                    "created_at": log.created_at.isoformat() + "Z" if log.created_at else None,
                    "gates_failed_json": log.gates_failed_json,
                    "gates_passed_json": log.gates_passed_json,
                }
            )
            if log.status == "preflight_blocked" or (
                not log.broker_order_id and log.status != "paper_order_submitted"
            ):
                preflight_blocked.append(row)
            elif log.status in (
                "paper_order_submitted",
                "paper_order_filled",
                "paper_order_partially_filled",
                "paper_order_rejected",
            ):
                submitted.append(row)
                gf = log.gates_failed_json if isinstance(log.gates_failed_json, dict) else {}
                if log.status == "paper_order_rejected" or gf.get("preflight_stage") == "broker_rejection":
                    broker_rejected.append(row)
                if log.status == "paper_order_filled":
                    filled.append(row)

        orders = list(
            self.session.exec(select(OrderRecord).order_by(OrderRecord.id.desc()).limit(50)).all()
        )
        order_rows = [
            enrich_order_record(
                {
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "status": o.status,
                    "broker_order_id": o.alpaca_order_id,
                    "broker_client_order_id": o.broker_client_order_id,
                }
            )
            for o in orders
        ]

        latest_submit = submitted[0] if submitted else None
        latest_block = preflight_blocked[0] if preflight_blocked else None

        return {
            "status": "ok",
            "reset_epoch": epoch,
            "counts": {
                "attempted": len(logs),
                "preflight_blocked": len(preflight_blocked),
                "submitted_to_broker": len(submitted),
                "broker_rejected": len(broker_rejected),
                "filled": len(filled),
                "orders_in_db": len(order_rows),
            },
            "latest_broker_order_id": (latest_submit or {}).get("broker_order_id"),
            "latest_client_order_id": (latest_submit or {}).get("broker_client_order_id"),
            "latest_submit": latest_submit,
            "latest_preflight_block": latest_block,
            "recent_submitted": submitted[:10],
            "recent_preflight_blocked": preflight_blocked[:10],
            "recent_orders": order_rows[:15],
            "plain": self._plain_summary(len(submitted), len(preflight_blocked), latest_submit, latest_block),
        }

    def _plain_summary(
        self,
        submitted_n: int,
        blocked_n: int,
        latest_submit: Optional[dict],
        latest_block: Optional[dict],
    ) -> str:
        if latest_submit and latest_submit.get("broker_order_id"):
            return (
                f"{submitted_n} paper order(s) reached Alpaca. "
                f"Latest: {latest_submit.get('symbol')} — {latest_submit.get('status_label')}."
            )
        if latest_block:
            return (
                f"No broker submit yet — {blocked_n} blocked before broker. "
                f"Latest block: {latest_block.get('symbol')} — {latest_block.get('reject_reason_plain') or latest_block.get('reject_reason')}."
            )
        return "No paper execution attempts recorded this epoch yet."
