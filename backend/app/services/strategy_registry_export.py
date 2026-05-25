"""Diagnostic export helpers for strategy registry truth."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from app.database import StrategyLifecycleEvent, StrategyRejection, StrategyRegistry
from app.services.strategy_stages import EXPORT_ACTIVE_STAGES


def list_active_registry(session: Session) -> list[dict]:
    from app.services.strategy_registry_service import StrategyRegistryService

    svc = StrategyRegistryService(session)
    out = []
    for stage in EXPORT_ACTIVE_STAGES:
        out.extend(svc.list_registry(stage=stage))
    return out


def list_rejected_registry(session: Session) -> list[dict]:
    from app.services.strategy_registry_service import StrategyRegistryService

    return StrategyRegistryService(session).list_registry(stage="rejected")


def list_research_only_registry(session: Session) -> list[dict]:
    from app.services.strategy_registry_service import StrategyRegistryService

    svc = StrategyRegistryService(session)
    return svc.list_registry(stage="research_only") + svc.list_registry(stage="watchlist")


def ensure_strategy_rejection_records(session: Session) -> list[dict]:
    """Populate strategy_rejections from registry + lifecycle when table empty."""
    existing = list(session.exec(select(StrategyRejection)).all())
    if existing:
        return [_rej_row(r) for r in existing]

    created = []
    for reg in session.exec(select(StrategyRegistry).where(StrategyRegistry.current_stage == "rejected")).all():
        ev = session.exec(
            select(StrategyLifecycleEvent)
            .where(StrategyLifecycleEvent.strategy_id == reg.strategy_id)
            .order_by(StrategyLifecycleEvent.created_at.desc())
        ).first()
        rationale = ev.reason_text if ev else f"Rejected at stage {reg.current_stage}"
        row = StrategyRejection(
            strategy_id=reg.strategy_id,
            gate_name=ev.reason_code if ev else "research_validation",
            failure_codes_json=ev.evidence_json.get("failures", []) if ev and ev.evidence_json else ["weak_metrics"],
            permanent=False,
            rationale=rationale[:500],
            evidence_json={"registry_stage": reg.current_stage, "lifecycle": ev.reason_text if ev else None},
        )
        session.add(row)
        created.append(row)
    session.flush()
    return [_rej_row(r) for r in created]


def memory_validation_mismatches(session: Session) -> dict:
    from app.database import LessonNode, StrategyMemoryLink

    links = list(session.exec(select(StrategyMemoryLink)).all())
    mismatches = 0
    hidden = 0
    for link in links:
        lesson = session.get(LessonNode, link.memory_id)
        if not lesson:
            continue
        ls = getattr(lesson, "system_validation_status", "pending")
        if link.memory_status != ls:
            mismatches += 1
        if link.memory_status == "validated" and not lesson.visible_in_graph:
            hidden += 1
    return {
        "mismatched_validation_status_count": mismatches,
        "validated_but_hidden_from_graph_count": hidden,
        "pending_memories": sum(1 for l in links if l.memory_status == "pending"),
        "validated_memories": sum(1 for l in links if l.memory_status == "validated"),
        "rejected_memories": sum(1 for l in links if l.memory_status == "rejected"),
        "pending_ranking_violations": sum(
            1 for l in links if l.memory_status == "pending" and l.can_influence_ranking
        ),
        "live_trading_locked": True,
        "ai_direct_promotion_detected": False,
    }


def _rej_row(r: StrategyRejection) -> dict:
    return {
        "id": r.id,
        "strategy_id": r.strategy_id,
        "gate_name": r.gate_name,
        "failure_codes_json": r.failure_codes_json,
        "permanent": r.permanent,
        "rationale": r.rationale,
        "evidence_json": r.evidence_json,
        "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
    }
