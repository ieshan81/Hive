"""Hive Brain API — graph, node detail, consolidation."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.config_manager import ConfigManager
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.hive_brain_node_service import HiveBrainNodeService
from app.services.memory_consolidation_service import MemoryConsolidationService
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/hive-brain", tags=["hive-brain"])


@router.get("/status")
def hive_brain_status(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    cons = MemoryConsolidationService(session, cfg).status()
    graph = HiveBrainGraphService(session, cfg).build_full()
    return {
        "status": "ok",
        "consolidation": cons,
        "graph_meta": graph.get("meta", {}),
        "visible_nodes": graph.get("meta", {}).get("visible_nodes"),
    }


@router.get("/graph")
def hive_brain_graph(
    show_raw: bool = False,
    expand_cluster: str | None = None,
    mode: str = "research",
    session: Session = Depends(get_session),
):
    cfg = ConfigManager(session).get_current()
    graph_mode = mode if mode in ("skeleton", "research", "validated", "default") else "research"
    try:
        return HiveBrainGraphService(session, cfg).build_full(
            show_raw=show_raw, expand_cluster=expand_cluster, graph_mode=graph_mode
        )
    except Exception as exc:
        out = HiveBrainGraphService(session, cfg).build_full(show_raw=False, graph_mode="skeleton")
        out["status"] = "degraded"
        out["error"] = str(exc)[:120]
        return out


@router.get("/node/{node_id}")
def hive_brain_node(node_id: str, session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return HiveBrainNodeService(session, cfg).get_node(node_id)


@router.get("/cluster/{cluster_id}")
def hive_brain_cluster(cluster_id: str, session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    graph = HiveBrainGraphService(session, cfg).build_full(expand_cluster=cluster_id)
    children = [n for n in graph.get("nodes", []) if n.get("cluster_id") == cluster_id or cluster_id in str(n.get("id", ""))]
    return {"status": "ok", "cluster_id": cluster_id, "children": children, "edges": graph.get("edges", [])}


@router.post("/rebuild")
def hive_brain_rebuild(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    cfg = ConfigManager(session).get_current()
    return HiveBrainGraphService(session, cfg).build_full(show_raw=bool(body.get("show_raw")))


@router.post("/consolidate")
def hive_brain_consolidate(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    cfg = ConfigManager(session).get_current()
    out = MemoryConsolidationService(session, cfg).run(force=bool(body.get("force")))
    session.commit()
    return out


@router.post("/archive-raw")
def hive_brain_archive_raw(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    cfg = ConfigManager(session).get_current()
    out = MemoryConsolidationService(session, cfg).archive_raw_duplicates()
    session.commit()
    return out
