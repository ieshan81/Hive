"""Post-cycle memory processing — triggers, patterns, backfill."""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, PositionSnapshot, StrategySignal
from app.services.config_manager import ConfigManager
from app.services.memory_patterns import run_pattern_scan
from app.services.memory_triggers import (
    on_ai_review_not_fresh,
    on_dashboard_truth_mismatch,
    on_duplicate_position_export,
    on_execution_failure,
    on_open_position_monitor,
    on_paper_order_filled,
    on_qty_fee_difference,
)


def _norm_symbol(s: str) -> str:
    return s.upper().replace("/", "").replace("-", "")


def process_cycle_memories(
    session: Session,
    cycle_run_id: str,
    summary: dict[str, Any],
    *,
    dashboard_truth_message: Optional[str] = None,
) -> dict[str, Any]:
    config = ConfigManager(session).get_current()
    created_ids: list[int] = []

    logs = session.exec(
        select(ExecutionLog).where(ExecutionLog.cycle_run_id == cycle_run_id)
    ).all()

    for log in logs:
        if log.status in ("paper_order_filled", "paper_order_partially_filled"):
            row = on_paper_order_filled(session, config, execution_log=log, cycle_run_id=cycle_run_id)
            created_ids.append(row.id)

            filled = float(log.filled_qty or 0)
            if filled > 0 and log.symbol:
                positions = session.exec(select(PositionSnapshot)).all()
                broker_qty = 0.0
                sym_norm = _norm_symbol(log.symbol)
                for p in positions:
                    if _norm_symbol(p.symbol) == sym_norm and (p.qty or 0) > 0:
                        broker_qty = max(broker_qty, float(p.qty))
                if broker_qty > 0:
                    fee_row = on_qty_fee_difference(
                        session,
                        config,
                        filled_qty=filled,
                        broker_position_qty=broker_qty,
                        symbol=log.symbol,
                        cycle_run_id=cycle_run_id,
                        broker_order_id=log.broker_order_id,
                        avg_entry_price=log.filled_avg_price,
                    )
                    if fee_row:
                        created_ids.append(fee_row.id)
        elif log.status in (
            "paper_order_rejected",
            "paper_order_cancelled",
            "paper_order_unfilled",
            "preflight_blocked",
        ):
            row = on_execution_failure(session, config, execution_log=log, cycle_run_id=cycle_run_id)
            created_ids.append(row.id)

    all_pos = session.exec(select(PositionSnapshot)).all()
    open_pos = [p for p in all_pos if (p.qty or 0) > 0]
    sym_counts = Counter(_norm_symbol(p.symbol) for p in open_pos)
    for sym, cnt in sym_counts.items():
        if cnt > 1:
            row = on_duplicate_position_export(
                session,
                config,
                symbol=sym,
                duplicate_count=cnt,
                broker_positions_count=1,
                exported_count=cnt,
                cycle_run_id=cycle_run_id,
            )
            created_ids.append(row.id)

    orders_submitted = summary.get("orders_submitted", 0)
    if dashboard_truth_message:
        low = dashboard_truth_message.lower()
        if orders_submitted > 0 and (
            "no tradeable" in low or "no order" in low and "disabled" not in low
        ):
            row = on_dashboard_truth_mismatch(
                session,
                config,
                dashboard_field="approvalMessage / truthMessage",
                dashboard_value=dashboard_truth_message,
                truth_value={"orders_submitted": orders_submitted},
                cycle_run_id=cycle_run_id,
            )
            created_ids.append(row.id)

    ai_meta = summary.get("ai_review_meta") or {}
    if ai_meta.get("ai_review_status") != "success":
        row = on_ai_review_not_fresh(
            session,
            config,
            latest_cycle_run_id=cycle_run_id,
            review_cycle_run_id=cycle_run_id if ai_meta.get("ai_review_status") == "success" else None,
            skip_reason=ai_meta.get("ai_review_error_message") or "skipped",
        )
        created_ids.append(row.id)

    for p in open_pos:
        sig = session.exec(
            select(StrategySignal).where(
                StrategySignal.symbol == p.symbol,
                StrategySignal.cycle_run_id == cycle_run_id,
            )
        ).first()
        stop = sig.stop_loss if sig else None
        meta = (sig.signal_metadata or {}) if sig else {}
        row = on_open_position_monitor(
            session,
            config,
            position=p,
            stop_loss=stop,
            max_hold_hours=meta.get("max_hold_hours"),
            cycle_run_id=cycle_run_id,
        )
        created_ids.append(row.id)

    pattern_ids = run_pattern_scan(session, config, cycle_run_id)
    created_ids.extend(pattern_ids)

    return {"lessons_created_or_updated": len(set(created_ids)), "lesson_ids": list(set(created_ids))}


def backfill_doge_cycle_if_present(session: Session, cycle_run_id: str = "8796825e-5f25-4cfa-b0f9-b0141f61859c") -> int:
    """Idempotent backfill for known DOGE paper fill cycle."""
    config = ConfigManager(session).get_current()
    logs = session.exec(
        select(ExecutionLog).where(ExecutionLog.cycle_run_id == cycle_run_id)
    ).all()
    if not logs:
        return 0
    summary = {"orders_submitted": 1, "ai_review_meta": {"ai_review_status": "success"}}
    result = process_cycle_memories(
        session,
        cycle_run_id,
        summary,
        dashboard_truth_message="No tradeable signals this cycle",
    )
    session.commit()
    return result["lessons_created_or_updated"]
