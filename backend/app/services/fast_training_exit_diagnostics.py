"""Diagnostic bundle exports for fast-training exit / preflight."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PaperExperimentOutcome
from app.services.config_manager import ConfigManager
from app.services.fast_training_exit_only_service import FastTrainingExitOnlyService
from app.services.open_position_review_service import OpenPositionReviewService


def _serialize_execution(row: ExecutionLog) -> dict[str, Any]:
    gf = row.gates_failed_json or {}
    gp = row.gates_passed_json or {}
    ev = gf.get("evidence") if isinstance(gf.get("evidence"), dict) else {}
    if not ev and isinstance(gp, dict):
        ev = gp.get("evidence") if isinstance(gp.get("evidence"), dict) else {}
    stage = "internal_preflight_block"
    if row.status in ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled"):
        stage = "caged_order_submitted"
    elif row.status == "paper_order_rejected":
        stage = "broker_rejection"
    elif gf.get("preflight_stage"):
        stage = gf.get("preflight_stage")
    exempt = ev.get("notional_exemption") or gf.get("notional_exemption")
    return {
        "id": row.id,
        "cycle_run_id": row.cycle_run_id,
        "symbol": row.symbol,
        "side": row.side,
        "signal_type": row.signal_type,
        "status": row.status,
        "reject_reason": row.reject_reason,
        "broker_order_id": row.broker_order_id,
        "requested_qty": row.requested_qty,
        "requested_notional": row.requested_notional,
        "preflight_stage": stage,
        "notional_exemption": exempt,
        "internal_preflight_passed": bool(gp.get("preflight")) if isinstance(gp, dict) else None,
        "gates_failed": gf,
        "gates_passed": gp,
        "submitted_at": row.submitted_at.isoformat() + "Z" if row.submitted_at else None,
    }


def build_exit_diagnostic_exports(session: Session, config: dict | None = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    exit_only = FastTrainingExitOnlyService(session, cfg)
    reviews = OpenPositionReviewService(session, cfg).review_all()

    exit_logs = list(
        session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.cycle_run_id.like("training-exit-%"))
            .order_by(ExecutionLog.id.desc())
            .limit(50)
        ).all()
    )
    sell_logs = list(
        session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.side == "sell")
            .order_by(ExecutionLog.id.desc())
            .limit(50)
        ).all()
    )

    orders = list(session.exec(select(OrderRecord).order_by(OrderRecord.id.desc()).limit(20)).all())
    outcomes = list(
        session.exec(
            select(PaperExperimentOutcome).order_by(PaperExperimentOutcome.id.desc()).limit(30)
        ).all()
    )

    preflight_rows = [_serialize_execution(r) for r in exit_logs + sell_logs]
    seen = set()
    unique_preflight = []
    for row in preflight_rows:
        key = row.get("id")
        if key in seen:
            continue
        seen.add(key)
        unique_preflight.append(row)

    return {
        "fast_training_exit_only_status.json": exit_only.status(),
        "open_position_reviews.json": reviews,
        "fast_training_exit_decisions.json": unique_preflight,
        "fast_training_exit_orders.json": {
            "order_records": [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "status": o.status,
                    "alpaca_order_id": o.alpaca_order_id,
                    "broker_client_order_id": o.broker_client_order_id,
                    "cycle_run_id": o.cycle_run_id,
                }
                for o in orders
            ],
            "execution_logs": [_serialize_execution(r) for r in exit_logs[:20]],
        },
        "training_outcomes.json": [
            {
                "id": o.id,
                "strategy_id": o.strategy_id,
                "symbol": o.symbol,
                "exit_reason": o.exit_reason,
                "hold_minutes": o.hold_minutes,
                "lesson_created": o.lesson_created,
            }
            for o in outcomes
        ],
        "preflight_decisions.json": unique_preflight,
    }
