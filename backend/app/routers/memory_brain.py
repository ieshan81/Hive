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
