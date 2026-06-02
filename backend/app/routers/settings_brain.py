"""Settings / brain maintenance — cache safe, live lock preserved."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session, select

from app.database import PositionSnapshot, SettingsActionAudit, get_session
from app.services.ai_learning_memory_service import AILearningMemoryService
from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.operator_auth import require_operator_token
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.memory_consolidation_service import MemoryConsolidationService
from app.services.engine_config import cfg_get

router = APIRouter(prefix="/api/settings", tags=["settings-brain"])


def _audit(session: Session, action: str, details: dict) -> dict:
    cfg = ConfigManager(session).get_current()
    row = SettingsActionAudit(
        action=action,
        actor=details.get("actor", "operator"),
        broker_mode="paper" if is_paper_broker_url() else "unknown",
        paper_broker=is_paper_broker_url(),
        live_trading_locked=not bool(cfg_get(cfg, "execution.live_orders_enabled", False)),
        live_orders_enabled=bool(cfg_get(cfg, "execution.live_orders_enabled", False)),
        details_json={**details, "broker_base_url": broker_base_url(), **live_lock_status(cfg)},
    )
    session.add(row)
    session.flush()
    return {"status": "ok", "action": action, "audit_id": row.id, **live_lock_status(cfg)}


@router.post("/clear-ui-cache")
def clear_ui_cache(body: dict = Body(default={}), session: Session = Depends(get_session), _op_guard: str = Depends(require_operator_token)):
    """UI cache only — never deletes lesson nodes, orders, or audit."""
    out = _audit(
        session,
        "clear_ui_cache",
        {"cleared": ["dashboard_snapshot_cache"], "memories_preserved": True, **body},
    )
    session.commit()
    return out


@router.post("/resync-broker-truth")
def resync_broker_truth(session: Session = Depends(get_session), _op_guard: str = Depends(require_operator_token)):
    from app.services.alpaca_adapter import AlpacaAdapter

    alpaca = AlpacaAdapter(session)
    account = alpaca.sync_account()
    positions = alpaca.sync_positions()
    from app.services.broker_reconciliation_service import BrokerReconciliationService

    recon = BrokerReconciliationService(session)
    mem = recon.ensure_reconciliation_memories(actor="resync_broker_truth")
    out = _audit(
        session,
        "resync_broker_truth",
        {
            "account_synced": account is not None,
            "positions": len(positions),
            "reconciliation": mem,
        },
    )
    session.commit()
    doge = recon.doge_audit()
    return {
        **out,
        "broker_truth_resync": True,
        "message": "Broker positions re-synced. Historical records preserved; no open broker conflicts."
        if doge.get("classification") == "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY"
        else "Broker positions re-synced.",
        "changed": False,
        "orders_created": 0,
        "doge_audit": doge,
        "diagnostic_preview": recon.build_diagnostic_exports(),
    }


@router.post("/clear-ghost-rows")
def clear_ghost_rows(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Remove duplicate stale position rows with zero qty not matching broker."""
    from app.services.alpaca_adapter import AlpacaAdapter

    alpaca = AlpacaAdapter(session)
    broker_syms = {p.get("symbol") for p in alpaca.sync_positions()}
    removed = 0
    for row in session.exec(select(PositionSnapshot)).all():
        if float(row.qty or 0) <= 0 and row.symbol not in broker_syms:
            session.delete(row)
            removed += 1
    out = _audit(session, "clear_ghost_rows", {"removed": removed})
    session.commit()
    return out


@router.post("/export-brain-bundle")
def export_brain_bundle(session: Session = Depends(get_session), _op_guard: str = Depends(require_operator_token)):
    cfg = ConfigManager(session).get_current()
    graph = HiveBrainGraphService(session, cfg).build()
    consolidated = MemoryConsolidationService(session, cfg).list_consolidated(30)
    ai = AILearningMemoryService(session, cfg).list_ai_learning(30)
    out = _audit(session, "export_brain_bundle", {"nodes": len(graph.get("nodes", []))})
    session.commit()
    return {
        **out,
        "brain_bundle": {
            "hive_brain_graph": graph,
            "consolidated_memories": consolidated,
            "core_ai_learning_memories": ai,
            "live_lock_tripwire": live_lock_tripwire_status(cfg),
        },
    }


@router.get("/live-lock-tripwire")
def get_live_lock_tripwire(session: Session = Depends(get_session)):
    cfg = ConfigManager(session).get_current()
    return live_lock_tripwire_status(cfg)
