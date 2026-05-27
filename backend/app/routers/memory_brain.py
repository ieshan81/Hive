"""Hive Brain memory consolidation and AI learning APIs."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.ai_learning_memory_service import AILearningMemoryService
from app.services.config_manager import ConfigManager
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.memory_consolidation_service import MemoryConsolidationService

router = APIRouter(prefix="/api/memory", tags=["memory-brain"])


@router.get("/consolidation/status")
def consolidation_status(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return MemoryConsolidationService(session, cfg).status()


# ─────────────────────────────────────────────────────────────────────────
# 5-tier memory quality endpoints (spec)
# ─────────────────────────────────────────────────────────────────────────

@router.get("/status")
def memory_status(session: Session = Depends(get_session)):
    """5-tier breakdown using memory_quality_service."""
    from datetime import datetime
    from app.services.memory_quality_service import MemoryQualityService

    svc = MemoryQualityService(session)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        **svc.status_summary(),
    }


@router.get("/quality")
def memory_quality(session: Session = Depends(get_session)):
    """Recompute quality scores + return per-tier counts."""
    from datetime import datetime
    from app.services.memory_quality_service import MemoryQualityService

    svc = MemoryQualityService(session)
    updates = svc.update_quality_scores()
    summary = svc.status_summary()
    session.commit()
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "quality_updates_applied": updates,
        "by_tier": summary["by_tier"],
        "promotion_floor": summary["promotion_floor"],
    }


@router.post("/promote-pass")
def memory_promote_pass(session: Session = Depends(get_session)):
    """Single promotion sweep across all active memories."""
    from datetime import datetime
    from app.services.memory_quality_service import MemoryQualityService

    svc = MemoryQualityService(session)
    result = svc.run_promotion_pass()
    session.commit()
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        **result,
    }


@router.get("/latest")
def memory_latest(limit: int = 25, session: Session = Depends(get_session)):
    """Most recent active memories across all tiers."""
    from datetime import datetime
    from sqlmodel import select
    from app.database import LessonNode
    from app.services.memory_quality_service import memory_tier

    rows = session.exec(
        select(LessonNode).where(LessonNode.status == "active").order_by(LessonNode.updated_at.desc()).limit(limit)
    ).all()
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "items": [
            {
                "id": r.id,
                "tier": memory_tier(r),
                "memory_type": r.memory_type,
                "title": r.title,
                "summary": r.summary,
                "symbol": r.symbol,
                "strategy": r.strategy_name,
                "occurrence_count": r.occurrence_count,
                "quality_score": r.importance_score,
                "confidence": r.confidence,
                "first_seen_at": r.first_seen_at.isoformat() + "Z" if r.first_seen_at else None,
                "last_seen_at": r.last_seen_at.isoformat() + "Z" if r.last_seen_at else None,
            }
            for r in rows
        ],
    }


@router.post("/consolidation/run")
def consolidation_run(body: dict = Body(default={}), session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    out = MemoryConsolidationService(session, cfg).run(force=bool(body.get("force")))
    session.commit()
    return out


@router.post("/consolidation/archive-raw")
def consolidation_archive_raw(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    out = MemoryConsolidationService(session, cfg).archive_raw_duplicates()
    session.commit()
    return out


@router.get("/consolidated")
def list_consolidated(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return {"status": "ok", "memories": MemoryConsolidationService(session, cfg).list_consolidated()}


@router.get("/ai-learning")
def list_ai_learning(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return {"status": "ok", "memories": AILearningMemoryService(session, cfg).list_ai_learning()}


@router.post("/ai-learning/generate")
def generate_ai_learning(body: dict = Body(default={}), session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    out = AILearningMemoryService(session, cfg).generate(force=bool(body.get("force")))
    session.commit()
    return out


@router.post("/graph/rebuild")
def graph_rebuild(body: dict = Body(default={}), session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    show_raw = bool(body.get("show_raw"))
    graph = HiveBrainGraphService(session, cfg).build(show_raw=show_raw)
    return graph
