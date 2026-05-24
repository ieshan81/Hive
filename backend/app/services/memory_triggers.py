"""Deterministic memory triggers — evidence first, no AI invention."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.database import ExecutionLog, LessonNode, PositionSnapshot
from app.services.lesson_memory_service import LessonMemoryService


def on_paper_order_filled(
    session: Session,
    config: dict,
    *,
    execution_log: ExecutionLog,
    cycle_run_id: str,
    strategy_name: str = "crypto_push_pull",
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    evidence = {
        "symbol": execution_log.symbol,
        "side": execution_log.side,
        "requested_qty": execution_log.requested_qty,
        "filled_qty": execution_log.filled_qty,
        "requested_notional": execution_log.requested_notional,
        "limit_price": execution_log.limit_price,
        "filled_avg_price": execution_log.filled_avg_price,
        "spread_pct_at_decision": execution_log.spread_pct_at_decision,
        "edge_over_cost": execution_log.edge_over_cost,
        "atr14_at_decision": execution_log.atr14_at_decision,
        "broker_order_id": execution_log.broker_order_id,
        "client_order_id": execution_log.broker_client_order_id,
        "tif": execution_log.tif,
        "order_type": "marketable_limit_ioc",
    }
    return svc.upsert_lesson(
        memory_type="trade_lesson",
        title=f"Paper {execution_log.side.upper()} filled: {execution_log.symbol}",
        summary=f"Top-1 paper order filled at {execution_log.filled_avg_price}",
        detailed_lesson=(
            "Caged execution selected Top-1 signal, passed preflight, and Alpaca paper fill confirmed. "
            "Use broker-confirmed position for exits and P/L."
        ),
        severity="MEDIUM",
        confidence=0.95,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        signal_id=execution_log.signal_id,
        broker_order_id=execution_log.broker_order_id,
        symbol=execution_log.symbol,
        strategy_name=strategy_name,
        related_entity_type="execution_log",
        related_entity_id=execution_log.event_id,
        evidence=evidence,
        pattern_key=f"trade_open|{execution_log.broker_order_id}",
        tags=["paper_fill", "top1"],
    )


def on_qty_fee_difference(
    session: Session,
    config: dict,
    *,
    filled_qty: float,
    broker_position_qty: float,
    symbol: str,
    cycle_run_id: str,
    broker_order_id: Optional[str] = None,
    avg_entry_price: Optional[float] = None,
) -> Optional[LessonNode]:
    if not filled_qty or not broker_position_qty:
        return None
    diff = float(filled_qty) - float(broker_position_qty)
    diff_pct = abs(diff) / float(filled_qty) * 100 if filled_qty else 0
    if diff_pct < 0.05:
        return None
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="fee_lesson",
        title=f"Broker net qty differs from filled qty ({symbol})",
        summary=f"Filled {filled_qty:.6f} vs broker position {broker_position_qty:.6f} ({diff_pct:.2f}% diff)",
        detailed_lesson=(
            "Alpaca crypto paper position quantity may reflect fee deduction or broker netting. "
            "Use broker-confirmed net position as final truth for exits and P/L."
        ),
        severity="HIGH" if diff_pct > 0.5 else "MEDIUM",
        confidence=0.92,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        symbol=symbol,
        broker_order_id=broker_order_id,
        related_entity_type="position",
        evidence={
            "filled_qty": filled_qty,
            "broker_position_qty": broker_position_qty,
            "difference_qty": diff,
            "difference_pct": diff_pct,
            "suspected_fee_pct": diff_pct,
            "avg_entry_price": avg_entry_price,
            "broker_source": "alpaca_paper",
        },
        proposed_action="Use broker net qty for exit sizing; add fee-aware reconciliation",
        pattern_key=f"fee_qty_diff|{symbol}",
        aggregate=True,
        tags=["fee", "reconciliation"],
    )


def on_duplicate_position_export(
    session: Session,
    config: dict,
    *,
    symbol: str,
    duplicate_count: int,
    broker_positions_count: int,
    exported_count: int,
    cycle_run_id: str,
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="reconciliation_bug",
        title=f"Duplicate position rows for {symbol}",
        summary=f"Exported {exported_count} rows but broker shows {broker_positions_count} position(s)",
        detailed_lesson=(
            "Position export/upsert must represent broker-confirmed current position uniquely. "
            "Deduplicate by symbol on sync and export."
        ),
        severity="HIGH",
        confidence=0.9,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        symbol=symbol,
        related_entity_type="position_export",
        evidence={
            "symbol": symbol,
            "duplicate_count": duplicate_count,
            "broker_positions_count": broker_positions_count,
            "exported_positions_count": exported_count,
            "cycle_run_id": cycle_run_id,
        },
        proposed_action="Unique broker-position upsert/export by symbol",
        pattern_key=f"dup_position|{symbol}",
        aggregate=True,
        tags=["reconciliation", "positions"],
    )


def on_dashboard_truth_mismatch(
    session: Session,
    config: dict,
    *,
    dashboard_field: str,
    dashboard_value: Any,
    truth_value: Any,
    cycle_run_id: str,
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="ui_truth_bug",
        title="Dashboard truth mismatch",
        summary=f"{dashboard_field}: dashboard={dashboard_value!s} vs truth={truth_value!s}",
        detailed_lesson=(
            "Dashboard must reflect latest cycle truth from execution logs and cycle summary, "
            "not stale AI review or generic messages."
        ),
        severity="HIGH",
        confidence=0.88,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        related_entity_type="dashboard",
        evidence={
            "dashboard_field": dashboard_field,
            "dashboard_value": dashboard_value,
            "bundle_or_cycle_truth": truth_value,
            "cycle_run_id": cycle_run_id,
        },
        proposed_action="Fix latest-cycle dashboard truth mapping",
        pattern_key=f"dashboard_truth|{dashboard_field}",
        aggregate=True,
        tags=["dashboard", "ui"],
    )


def on_ai_review_not_fresh(
    session: Session,
    config: dict,
    *,
    latest_cycle_run_id: str,
    review_cycle_run_id: Optional[str],
    skip_reason: str,
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="ai_review_issue",
        title="AI review not fresh for latest cycle",
        summary=f"Latest cycle {latest_cycle_run_id[:8]}… review={review_cycle_run_id or 'none'} ({skip_reason})",
        detailed_lesson="AI review must match latest cycle or show explicit skipped reason; do not show stale review as current.",
        severity="MEDIUM",
        confidence=0.85,
        source="deterministic",
        cycle_run_id=latest_cycle_run_id,
        evidence={
            "latest_cycle_run_id": latest_cycle_run_id,
            "review_cycle_run_id": review_cycle_run_id,
            "skip_reason": skip_reason,
        },
        pattern_key="ai_review_stale",
        aggregate=True,
        tags=["ai", "freshness"],
    )


def on_execution_failure(
    session: Session,
    config: dict,
    *,
    execution_log: ExecutionLog,
    cycle_run_id: str,
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="execution_lesson",
        title=f"Paper order {execution_log.status}: {execution_log.symbol}",
        summary=execution_log.reject_reason or execution_log.status,
        detailed_lesson="Paper order did not fill; do not chase in same cycle. Review spread, limit buffer, and cooldown.",
        severity="MEDIUM",
        confidence=0.9,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        signal_id=execution_log.signal_id,
        symbol=execution_log.symbol,
        broker_order_id=execution_log.broker_order_id,
        evidence={
            "status": execution_log.status,
            "reject_reason": execution_log.reject_reason,
            "limit_price": execution_log.limit_price,
            "spread_pct": execution_log.spread_pct_at_decision,
            "gates_failed": execution_log.gates_failed_json,
        },
        pattern_key=f"exec_fail|{execution_log.symbol}|{execution_log.status}",
        aggregate=True,
    )


def on_repeated_risk_block(
    session: Session,
    config: dict,
    *,
    symbol: str,
    block_reason_code: str,
    count: int,
    strategy_name: Optional[str],
    cycle_run_id: str,
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="blocked_trade_pattern",
        title=f"Repeated risk block: {block_reason_code}",
        summary=f"{symbol or 'multiple'} blocked {count}x with {block_reason_code}",
        detailed_lesson="Consider symbol cooldown or threshold review for repeated blocks.",
        severity="MEDIUM",
        confidence=0.8,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        symbol=symbol,
        strategy_name=strategy_name,
        evidence={"block_reason_code": block_reason_code, "count": count},
        proposed_action="symbol cooldown or strategy threshold review",
        pattern_key=f"risk_block|{symbol}|{block_reason_code}",
        aggregate=True,
    )


def on_open_position_monitor(
    session: Session,
    config: dict,
    *,
    position: PositionSnapshot,
    stop_loss: Optional[float],
    max_hold_hours: Optional[float],
    cycle_run_id: str,
) -> LessonNode:
    svc = LessonMemoryService(session, config)
    return svc.upsert_lesson(
        memory_type="position_management_lesson",
        title=f"Monitor open position: {position.symbol}",
        summary=f"Qty {position.qty} unrealized P/L {position.unrealized_pl}",
        detailed_lesson="Exit monitor must check stop, take profit, momentum reversal, max hold, and kill switch.",
        severity="LOW",
        confidence=0.75,
        source="deterministic",
        cycle_run_id=cycle_run_id,
        symbol=position.symbol,
        evidence={
            "qty": position.qty,
            "avg_entry_price": position.avg_entry_price,
            "unrealized_pl": position.unrealized_pl,
            "stop_loss": stop_loss,
            "max_hold_hours": max_hold_hours,
        },
        pattern_key=f"position_monitor|{position.symbol}",
        aggregate=True,
    )
