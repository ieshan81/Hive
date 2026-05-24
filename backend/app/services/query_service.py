"""API query helpers — latest cycle, clean JSON rows."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    AIReview,
    ActivityLog,
    BlockedTrade,
    ExecutionLog,
    PortfolioDecision,
    RiskEvent,
    StrategySignal,
    SystemHealth,
)
from app.services.cycle_persistence import latest_cycle_end, _risk_event_cycle_id
from app.services.diagnostic_export import (
    serialize_activity,
    serialize_blocked_trade,
    serialize_execution_log,
    serialize_portfolio_decision,
    serialize_risk_event,
    serialize_strategy_signal,
)


def resolve_cycle_run_id(session: Session, cycle_run_id: str) -> Optional[str]:
    if cycle_run_id and cycle_run_id != "latest":
        return cycle_run_id
    log = latest_cycle_end(session)
    if log and log.details:
        return log.details.get("cycle_run_id")
    health = session.get(SystemHealth, 1)
    if health and health.details:
        return health.details.get("cycle_run_id") or (health.details.get("last_cycle") or {}).get(
            "cycle_run_id"
        )
    return None


def signals_for_cycle(session: Session, cycle_run_id: str) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(
        select(StrategySignal)
        .where(StrategySignal.cycle_run_id == cid)
        .order_by(StrategySignal.created_at.desc())
    ).all()
    return [serialize_strategy_signal(r) for r in rows]


def blocked_for_cycle(session: Session, cycle_run_id: str) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(
        select(BlockedTrade).where(BlockedTrade.cycle_run_id == cid).order_by(BlockedTrade.created_at.desc())
    ).all()
    return [serialize_blocked_trade(r) for r in rows]


def risk_events_for_cycle(session: Session, cycle_run_id: str) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(
        select(RiskEvent).where(RiskEvent.event_type == "trade_blocked").order_by(RiskEvent.created_at.desc())
    ).all()
    return [serialize_risk_event(r) for r in rows if _risk_event_cycle_id(r) == cid]


def portfolio_decisions_for_cycle(session: Session, cycle_run_id: str) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(
        select(PortfolioDecision)
        .where(PortfolioDecision.cycle_run_id == cid)
        .order_by(PortfolioDecision.portfolio_rank.asc())
    ).all()
    return [serialize_portfolio_decision(r) for r in rows]


def execution_logs_for_cycle(session: Session, cycle_run_id: str) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(
        select(ExecutionLog).where(ExecutionLog.cycle_run_id == cid).order_by(ExecutionLog.created_at.desc())
    ).all()
    return [serialize_execution_log(r) for r in rows]


def reviews_for_cycle(session: Session, cycle_run_id: str) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(select(AIReview).order_by(AIReview.created_at.desc()).limit(20)).all()
    out = []
    for r in rows:
        payload = r.payload or {}
        if payload.get("cycle_run_id") == cid or r.subject_id == cid:
            out.append(
                {
                    "id": r.id,
                    "subject_type": r.subject_type,
                    "decision": r.decision,
                    "review_status": r.review_status,
                    "confidence": r.confidence,
                    "summary": r.summary,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                }
            )
    return out
