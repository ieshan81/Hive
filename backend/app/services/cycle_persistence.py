"""Cycle persistence verification — bundle truth must match DB."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from sqlmodel import Session, select, func

from app.config import settings
from app.database import (
    ActivityLog,
    BlockedTrade,
    RiskEvent,
    StrategySignal,
    StrategyState,
)


def database_fingerprint() -> str:
    url = settings.resolve_database_url() or "unset"
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _risk_event_cycle_id(row: RiskEvent) -> Optional[str]:
    if not row.details:
        return None
    evidence = row.details.get("evidence") or {}
    return evidence.get("cycle_run_id") or row.details.get("cycle_run_id")


def count_cycle_rows(session: Session, cycle_run_id: Optional[str] = None) -> dict[str, int]:
    if cycle_run_id:
        sig_q = select(func.count()).select_from(StrategySignal).where(
            StrategySignal.cycle_run_id == cycle_run_id
        )
        blk_q = select(func.count()).select_from(BlockedTrade).where(
            BlockedTrade.cycle_run_id == cycle_run_id
        )
        risk_rows = session.exec(
            select(RiskEvent).where(RiskEvent.event_type == "trade_blocked")
        ).all()
        risk_count = sum(1 for r in risk_rows if _risk_event_cycle_id(r) == cycle_run_id)
        return {
            "strategy_signals": session.exec(sig_q).one(),
            "blocked_trades": session.exec(blk_q).one(),
            "risk_events": risk_count,
            "strategy_states": session.exec(select(func.count()).select_from(StrategyState)).one(),
        }

    return {
        "strategy_signals": session.exec(select(func.count()).select_from(StrategySignal)).one(),
        "blocked_trades": session.exec(select(func.count()).select_from(BlockedTrade)).one(),
        "risk_events": session.exec(
            select(func.count()).select_from(RiskEvent).where(RiskEvent.event_type == "trade_blocked")
        ).one(),
        "strategy_states": session.exec(select(func.count()).select_from(StrategyState)).one(),
    }


def latest_cycle_end(session: Session) -> ActivityLog | None:
    return session.exec(
        select(ActivityLog)
        .where(ActivityLog.event_type == "cycle_end")
        .order_by(ActivityLog.created_at.desc())
    ).first()


def verify_cycle_persistence(session: Session, summary: dict[str, Any]) -> dict[str, Any]:
    session.commit()
    session.expire_all()
    cycle_run_id = summary.get("cycle_run_id")
    counts = count_cycle_rows(session, cycle_run_id)
    verification = {
        "database_fingerprint": database_fingerprint(),
        "cycle_run_id": cycle_run_id,
        "persisted_strategy_signals": counts["strategy_signals"],
        "persisted_blocked_trades": counts["blocked_trades"],
        "persisted_risk_events": counts["risk_events"],
        "expected_signals_created": summary.get("signals_created", 0),
        "expected_blocked": summary.get("blocked", 0),
        "expected_approved": summary.get("approved", 0),
        "signals_match": counts["strategy_signals"] == summary.get("signals_created", 0),
        "blocked_match": counts["blocked_trades"] == summary.get("blocked", 0),
        "risk_events_match": counts["risk_events"] == summary.get("blocked", 0),
    }
    if not verification["signals_match"] or not verification["blocked_match"] or not verification["risk_events_match"]:
        summary.setdefault("errors", []).append(
            f"Persistence mismatch: DB signals={counts['strategy_signals']} blocked={counts['blocked_trades']} "
            f"risk={counts['risk_events']} expected signals={summary.get('signals_created')} "
            f"blocked={summary.get('blocked')}"
        )
    summary["persistence"] = verification
    summary["database_fingerprint"] = database_fingerprint()
    return summary
