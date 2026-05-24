"""Latest-cycle decision drilldowns for UI."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    BlockedTrade,
    ExecutionLog,
    LessonNode,
    PortfolioDecision,
    StrategySignal,
)
from app.services.memory_categories import drawer_title
from app.services.query_service import resolve_cycle_run_id


def _signal_map(session: Session, cycle_id: str) -> dict[int, StrategySignal]:
    rows = session.exec(select(StrategySignal).where(StrategySignal.cycle_run_id == cycle_id)).all()
    return {s.id: s for s in rows if s.id}


def _row_signal(sig: Optional[StrategySignal]) -> dict[str, Any]:
    if not sig:
        return {}
    meta = sig.signal_metadata or {}
    return {
        "signal_id": sig.id,
        "symbol": sig.symbol,
        "side": sig.side,
        "signal_type": sig.signal_type,
        "strategy": sig.strategy,
        "risk_status": sig.status,
        "confidence": sig.confidence,
        "stop_loss": sig.stop_loss,
        "take_profit": sig.take_profit,
        "edge_over_cost": meta.get("edge_over_cost"),
        "expected_move_pct": meta.get("expected_move_pct"),
    }


def latest_summary(session: Session, cycle_run_id: str = "latest") -> dict[str, Any]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return {"status": "ok", "cycle_run_id": None, "counts": {}}
    sigs = _signal_map(session, cid)
    approved = approved_decisions(session, cid, sigs)
    blocked = blocked_decisions(session, cid)
    deferred = deferred_decisions(session, cid, sigs)
    orders = orders_decisions(session, cid)
    lessons = lessons_decisions(session, cid)
    observations = [
        _row_signal(s)
        for s in sigs.values()
        if s.status in ("observation", "downtrend", "watch_only")
    ]
    return {
        "status": "ok",
        "cycle_run_id": cid,
        "approved": approved,
        "blocked": blocked,
        "deferred": deferred,
        "observations": observations,
        "orders_submitted": orders,
        "lessons_created": lessons,
        "counts": {
            "approved": len(approved),
            "blocked": len(blocked),
            "deferred": len(deferred),
            "observations": len(observations),
            "orders": len(orders),
            "lessons": len(lessons),
        },
    }


def approved_decisions(
    session: Session,
    cycle_run_id: str = "latest",
    sig_map: Optional[dict[int, StrategySignal]] = None,
) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    sig_map = sig_map or _signal_map(session, cid)
    decs = session.exec(
        select(PortfolioDecision).where(
            PortfolioDecision.cycle_run_id == cid,
            PortfolioDecision.portfolio_status == "portfolio_approved",
        )
    ).all()
    exec_by_sig: dict[int, ExecutionLog] = {}
    for el in session.exec(
        select(ExecutionLog).where(ExecutionLog.cycle_run_id == cid)
    ).all():
        if el.signal_id:
            exec_by_sig[el.signal_id] = el

    out = []
    for d in decs:
        sig = sig_map.get(d.signal_id)
        el = exec_by_sig.get(d.signal_id)
        ev = d.evidence_json or {}
        out.append(
            {
                **(_row_signal(sig)),
                "portfolio_status": d.portfolio_status,
                "portfolio_rank": d.portfolio_rank,
                "ranking_score": d.ranking_score,
                "selected_for_execution": d.selected_for_execution,
                "portfolio_reason": d.human_reason,
                "execution_status": el.status if el else None,
                "order_submitted": el is not None
                and el.status in ("paper_order_submitted", "paper_order_filled"),
                "broker_order_id": el.broker_order_id if el else None,
                "rank": d.portfolio_rank,
                "reason": d.human_reason or d.portfolio_reason_code,
            }
        )
    return out


def blocked_decisions(session: Session, cycle_run_id: str = "latest") -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    risk_blocks = session.exec(
        select(BlockedTrade).where(BlockedTrade.cycle_run_id == cid)
    ).all()
    port_blocks = session.exec(
        select(PortfolioDecision).where(
            PortfolioDecision.cycle_run_id == cid,
            PortfolioDecision.portfolio_status == "portfolio_blocked",
        )
    ).all()
    sig_map = _signal_map(session, cid)
    out: list[dict[str, Any]] = []
    cycle_lessons = list(session.exec(select(LessonNode).where(LessonNode.cycle_run_id == cid)).all())
    for b in risk_blocks:
        mem = next(
            (
                m
                for m in cycle_lessons
                if m.symbol == b.symbol and "block" in (m.memory_type or "")
            ),
            None,
        )
        ev = b.evidence_json if isinstance(b.evidence_json, dict) else {}
        out.append(
            {
                "symbol": b.symbol,
                "strategy": b.strategy or "",
                "side": b.side or "",
                "block_reason_code": b.block_reason_code or b.reason,
                "human_reason": b.human_reason or b.reason,
                "risk_rule": b.risk_rule or "",
                "severity": ev.get("severity", "MEDIUM"),
                "evidence_summary": str(ev)[:200],
                "related_memory_id": mem.id if mem else None,
                "related_memory_title": mem.title if mem else None,
                "source": "risk",
            }
        )
    for d in port_blocks:
        sig = sig_map.get(d.signal_id)
        out.append(
            {
                **(_row_signal(sig)),
                "block_reason_code": d.portfolio_reason_code,
                "human_reason": d.human_reason,
                "risk_rule": "portfolio_gate",
                "severity": "MEDIUM",
                "evidence_summary": str(d.evidence_json or {})[:200],
                "source": "portfolio",
            }
        )
    return out


def deferred_decisions(
    session: Session,
    cycle_run_id: str = "latest",
    sig_map: Optional[dict[int, StrategySignal]] = None,
) -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    sig_map = sig_map or _signal_map(session, cid)
    decs = session.exec(
        select(PortfolioDecision).where(
            PortfolioDecision.cycle_run_id == cid,
            PortfolioDecision.portfolio_status == "portfolio_deferred",
        )
    ).all()
    return [
        {
            **(_row_signal(sig_map.get(d.signal_id))),
            "rank": d.portfolio_rank,
            "reason_code": d.portfolio_reason_code,
            "human_reason": d.human_reason,
            "ranking_score": d.ranking_score,
            "evidence": d.evidence_json,
        }
        for d in decs
    ]


def orders_decisions(session: Session, cycle_run_id: str = "latest") -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    logs = session.exec(
        select(ExecutionLog).where(ExecutionLog.cycle_run_id == cid)
    ).all()
    return [
        {
            "symbol": el.symbol,
            "side": el.side,
            "order_type": "marketable_limit_ioc",
            "tif": el.tif,
            "limit_price": el.limit_price,
            "requested_qty": el.requested_qty,
            "requested_notional": el.requested_notional,
            "filled_qty": el.filled_qty,
            "filled_avg_price": el.filled_avg_price,
            "broker_order_id": el.broker_order_id,
            "client_order_id": el.broker_client_order_id,
            "status": el.status,
            "reject_reason": el.reject_reason,
            "submitted_at": el.submitted_at.isoformat() + "Z" if el.submitted_at else None,
        }
        for el in logs
        if el.status not in ("pending",)
    ]


def lessons_decisions(session: Session, cycle_run_id: str = "latest") -> list[dict[str, Any]]:
    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return []
    rows = session.exec(
        select(LessonNode).where(LessonNode.cycle_run_id == cid)
    ).all()
    return [
        {
            "id": r.id,
            "node_id": f"lesson-{r.id}",
            "title": r.title,
            "category": r.category,
            "memory_type": r.memory_type,
            "severity": r.severity,
            "source": r.source,
            "action_status": r.action_status,
            "status": r.status,
            "drawer_title": drawer_title(r.category),
        }
        for r in rows
    ]
