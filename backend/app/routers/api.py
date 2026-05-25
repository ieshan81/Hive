from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response
from sqlmodel import Session

from app.database import get_session
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.ai_fund_manager import AIFundManager
from app.services.attention_radar_service import AttentionRadarService
from app.services.config_manager import ConfigManager
from app.services.dashboard_service import build_dashboard
from app.services.diagnostic_export import bundle_as_zip_bytes, export_diagnostic_bundle
from app.services.lab_service import LabService
from app.services.research_lab_service import ResearchLabService
from app.services.strategy_library import list_strategies
from app.services.historical_data_service import HistoricalDataService
from app.services.query_service import (
    blocked_for_cycle,
    resolve_cycle_run_id,
    reviews_for_cycle,
    risk_events_for_cycle,
    signals_for_cycle,
)
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.ai_lab_service import build_compact_cycle_context
from app.services.memory_engine import MemoryEngine

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/dashboard")
def get_dashboard(session: Session = Depends(get_session)):
    return build_dashboard(session)


@router.get("/health")
def health_check(session: Session = Depends(get_session)):
    from app.config import settings
    from app.database import SystemHealth

    health = session.get(SystemHealth, 1)
    warnings = []
    if not settings.alpaca_configured:
        warnings.append("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
    if not settings.gemini_configured:
        warnings.append("GEMINI_API_KEY not set")
    if not settings.database_url:
        warnings.append("DATABASE_URL not set")
    budget = AIBudgetGuard(session).status()

    return {
        "status": "ok",
        "service": "caged-hive-quant-api",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "alpaca_connected": health.alpaca_connected if health else False,
        "ai_budget": budget,
        "gemini_model_quick": settings.gemini_model_for("quick"),
        "gemini_model_deep": settings.gemini_model_for("deep"),
        "warnings": warnings,
    }


@router.post("/cycle/run")
def run_cycle(session: Session = Depends(get_session)):
    from app.services.cycle_engine import CycleEngine

    result = CycleEngine(session).run()
    session.commit()
    session.expire_all()
    return result


@router.get("/session")
def get_session_state(session: Session = Depends(get_session)):
    from app.services.session_engine import SessionEngine
    from app.services.activity_logger import log_activity

    state = SessionEngine().detect()
    log_activity(session, "session_check", f"Session: {state.mode}", state.to_dict())
    return state.to_dict()


@router.post("/radar/refresh")
def refresh_radar(session: Session = Depends(get_session)):
    config = ConfigManager(session).get_current()
    from app.services.market_radar_service import MarketRadarService
    from app.services.session_engine import SessionEngine

    session_state = SessionEngine().detect()
    candidates = MarketRadarService(session, config).refresh(session_state)
    return {"status": "ok", "count": len(candidates), "mode": session_state.mode}


@router.get("/radar/attention")
def attention_radar(limit: int = 25, session: Session = Depends(get_session)):
    return AttentionRadarService(session).scan(limit=min(max(limit, 1), 50))


@router.get("/symbols/discover")
def discover_symbols(
    asset_class: str = "all",
    limit: int = 25,
    session: str = "auto",
    refresh: bool = False,
    db: Session = Depends(get_session),
):
    from app.services.symbol_discovery_service import SymbolDiscoveryService

    if asset_class not in ("stock", "crypto", "all"):
        return {"status": "error", "message": "asset_class must be stock, crypto, or all"}
    if session not in ("auto", "stock_day", "crypto_night", "closed"):
        return {"status": "error", "message": "session must be auto, stock_day, crypto_night, or closed"}
    return SymbolDiscoveryService(db).discover(
        asset_class=asset_class,
        limit=min(max(limit, 1), 100),
        session_mode=session,
        refresh=refresh,
    )


@router.get("/strategy/signals")
def get_strategy_signals(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = signals_for_cycle(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "signals": rows}


@router.get("/risk/events")
def get_risk_events(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = risk_events_for_cycle(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "events": rows}


@router.get("/trades/blocked")
def get_blocked_trades(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = blocked_for_cycle(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "blocked_trades": rows}


@router.get("/portfolio/decisions")
def get_portfolio_decisions(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.query_service import portfolio_decisions_for_cycle

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = portfolio_decisions_for_cycle(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "decisions": rows}


@router.get("/execution/logs")
def get_execution_logs(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.query_service import execution_logs_for_cycle

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = execution_logs_for_cycle(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "execution_logs": rows}


@router.get("/execution/paper/status")
def paper_execution_status(session: Session = Depends(get_session)):
    from app.services.paper_execution_service import PaperExecutionService

    return PaperExecutionService(session).status()


@router.post("/execution/paper/enable")
def enable_paper_execution(session: Session = Depends(get_session)):
    from app.services.paper_execution_service import PaperExecutionService

    return PaperExecutionService(session).enable()


@router.post("/execution/paper/disable")
def disable_paper_execution(session: Session = Depends(get_session)):
    from app.services.paper_execution_service import PaperExecutionService

    return PaperExecutionService(session).disable()


@router.post("/execution/paper/run-selected")
def run_selected_paper_orders(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.paper_execution_service import PaperExecutionService

    cid = resolve_cycle_run_id(session, cycle_run_id)
    if not cid:
        return {"status": "error", "message": "No cycle run id"}
    return PaperExecutionService(session).run_selected_for_cycle(cid)


@router.get("/orders")
def get_orders(cycle_run_id: str = "latest", limit: int = 50, session: Session = Depends(get_session)):
    from app.services.positions_tab_service import orders_history

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = orders_history(session, limit=min(limit, 100))
    if cid:
        rows = [r for r in rows if r.get("cycle_run_id") == cid or not r.get("cycle_run_id")]
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "orders": rows}


@router.get("/positions")
def get_positions(session: Session = Depends(get_session)):
    from app.services.positions_tab_service import current_positions

    out = current_positions(session)
    return {"status": "ok", "count": len(out), "positions": out}


@router.get("/reconciliation/status")
def get_reconciliation_status(session: Session = Depends(get_session)):
    from app.services.order_reconciliation import reconciliation_status

    return {"status": "ok", **reconciliation_status(session, AlpacaAdapter(session))}


@router.post("/reconciliation/run")
def run_reconciliation(session: Session = Depends(get_session)):
    from app.services.order_reconciliation import reconciliation_status

    alpaca = AlpacaAdapter(session)
    result = reconciliation_status(session, alpaca)
    session.commit()
    return {"status": "ok", **result}


@router.get("/cooldowns")
def get_cooldowns(session: Session = Depends(get_session)):
    from app.services.cooldown_service import CooldownService

    config = ConfigManager(session).get_current()
    return {"status": "ok", **CooldownService(session, config).list_all()}


@router.get("/kill-switch/status")
def kill_switch_status(session: Session = Depends(get_session)):
    from app.services.kill_switch_service import KillSwitchService

    config = ConfigManager(session).get_current()
    return {"status": "ok", **KillSwitchService(session, config).status()}


@router.post("/kill-switch/manual/activate")
def kill_switch_activate(session: Session = Depends(get_session)):
    from app.services.kill_switch_service import KillSwitchService

    config = ConfigManager(session).get_current()
    ks = KillSwitchService(session, config)
    ev = ks.activate("manual_master", "Manual master kill activated by operator")
    config.setdefault("kill", {})["manual_master_active"] = True
    ConfigManager(session)._activate(config, changed_by="operator", reason="Manual kill on")
    return {"status": "ok", "event_id": ev.id}


@router.post("/kill-switch/manual/deactivate")
def kill_switch_deactivate(session: Session = Depends(get_session)):
    from app.services.kill_switch_service import KillSwitchService

    config = ConfigManager(session).get_current()
    KillSwitchService(session, config).deactivate_manual()
    config.setdefault("kill", {})["manual_master_active"] = False
    config["kill_switch_active"] = False
    ConfigManager(session)._activate(config, changed_by="operator", reason="Manual kill off")
    return {"status": "ok", "entries_allowed": True}


@router.get("/promotion/status")
def promotion_status(session: Session = Depends(get_session)):
    from app.services.promotion_service import PromotionService

    config = ConfigManager(session).get_current()
    return {"status": "ok", **PromotionService(session, config).status()}


@router.post("/promotion/request")
def promotion_request(target_stage: str = "PRE_LIVE", session: Session = Depends(get_session)):
    from app.services.promotion_service import PromotionService

    config = ConfigManager(session).get_current()
    return PromotionService(session, config).request_promotion(target_stage)


@router.get("/memory/graph")
def memory_graph(
    category: str | None = None,
    severity: str | None = None,
    include_archived: bool = False,
    graph_default: bool = True,
    session: Session = Depends(get_session),
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    graph = LessonMemoryService(session, config).build_graph(
        category=category,
        severity=severity,
        include_archived=include_archived,
        graph_default=graph_default,
    )
    return {"status": "ok", **graph}


@router.get("/memory/hive-mind")
def memory_hive_mind(session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService
    from app.services.ai_budget_guard import AIBudgetGuard
    from app.services.query_service import resolve_cycle_run_id
    from sqlmodel import select
    from app.database import AIReview

    config = ConfigManager(session).get_current()
    svc = LessonMemoryService(session, config)
    latest_cid = resolve_cycle_run_id(session, "latest")
    latest_review = session.exec(select(AIReview).order_by(AIReview.created_at.desc())).first()
    review_cid = (latest_review.payload or {}).get("cycle_run_id") if latest_review else None
    freshness = "latest"
    skip_reason = None
    if not latest_review:
        freshness = "none"
    elif latest_cid and review_cid != latest_cid:
        freshness = "stale"
    if latest_review and (latest_review.review_status or "").lower() in ("skipped", "skip"):
        freshness = "skipped"
        skip_reason = (latest_review.payload or {}).get("skip_reason", "rate_or_daily_limit")
    return {
        "status": "ok",
        **svc.hive_mind_summary(),
        "ai_review_freshness": {
            "latest_cycle_run_id": latest_cid,
            "review_cycle_run_id": review_cid,
            "freshness": freshness,
            "skip_reason": skip_reason,
        },
        "ai_budget": AIBudgetGuard(session).status(),
    }


@router.get("/memory/node/{node_id}")
def memory_node_detail(node_id: str, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    detail = LessonMemoryService(session, config).get_lesson(node_id)
    if not detail:
        return {"status": "error", "message": "Node not found"}
    return {"status": "ok", "node": detail}


@router.get("/memory/lessons")
def memory_lessons(
    symbol: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    memory_type: str | None = None,
    cycle_run_id: str | None = None,
    strategy_name: str | None = None,
    action_status: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    rows = LessonMemoryService(session, config).list_lessons(
        symbol=symbol,
        category=category,
        severity=severity,
        memory_type=memory_type,
        cycle_run_id=cycle_run_id,
        strategy_name=strategy_name,
        action_status=action_status,
        include_archived=include_archived,
        limit=limit,
    )
    return {"status": "ok", "count": len(rows), "lessons": rows}


@router.post("/memory/operator-note")
def memory_operator_note(
    title: str,
    summary: str,
    detailed_lesson: str = "",
    symbol: str | None = None,
    severity: str = "MEDIUM",
    session: Session = Depends(get_session),
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).upsert_lesson(
        memory_type="operator_note",
        title=title,
        summary=summary,
        detailed_lesson=detailed_lesson or summary,
        severity=severity,
        source="human_approved",
        symbol=symbol,
        action_status="approved",
    )
    session.commit()
    return {"status": "ok", "lesson_id": row.id}


@router.post("/memory/lesson/{lesson_id}/approve")
def memory_lesson_approve(lesson_id: int, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).approve(lesson_id)
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/lesson/{lesson_id}/reject")
def memory_lesson_reject(lesson_id: int, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).reject(lesson_id)
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/lesson/{lesson_id}/archive")
def memory_lesson_archive(
    lesson_id: int,
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).archive(
        lesson_id,
        reason=body.get("reason", ""),
        hide_from_ai=body.get("hide_from_ai", True),
        hide_from_graph=body.get("hide_from_graph", True),
    )
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/lesson/{lesson_id}/restore")
def memory_lesson_restore(lesson_id: int, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).restore(lesson_id)
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/lesson/{lesson_id}/delete")
def memory_lesson_delete(
    lesson_id: int,
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).soft_delete(
        lesson_id, reason=body.get("reason", "")
    )
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/lesson/{lesson_id}/resolve")
def memory_lesson_resolve(lesson_id: int, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).mark_resolved(lesson_id)
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/lesson/{lesson_id}/visibility")
def memory_lesson_visibility(
    lesson_id: int,
    body: dict,
    session: Session = Depends(get_session),
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).set_visibility(
        lesson_id,
        visible_to_ai=body.get("visible_to_ai"),
        visible_in_graph=body.get("visible_in_graph"),
        can_influence_ranking=body.get("can_influence_ranking"),
    )
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.post("/memory/bulk/archive")
def memory_bulk_archive(body: dict, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    ids = body.get("lesson_ids") or []
    n = LessonMemoryService(session, config).bulk_archive(
        ids,
        reason=body.get("reason", ""),
        hide_from_ai=body.get("hide_from_ai", True),
        hide_from_graph=body.get("hide_from_graph", True),
    )
    session.commit()
    return {"status": "ok", "archived": n}


@router.post("/memory/bulk/restore")
def memory_bulk_restore(body: dict, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    n = LessonMemoryService(session, config).bulk_restore(body.get("lesson_ids") or [])
    session.commit()
    return {"status": "ok", "restored": n}


@router.post("/memory/bulk/delete")
def memory_bulk_delete(body: dict, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    n = LessonMemoryService(session, config).bulk_soft_delete(
        body.get("lesson_ids") or [], reason=body.get("reason", "")
    )
    session.commit()
    return {"status": "ok", "deleted": n}


@router.post("/memory/bulk/hide-from-ai")
def memory_bulk_hide_ai(body: dict, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    n = LessonMemoryService(session, config).bulk_hide_from_ai(body.get("lesson_ids") or [])
    session.commit()
    return {"status": "ok", "updated": n}


@router.post("/memory/bulk/set-category")
def memory_bulk_category(body: dict, session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    n = LessonMemoryService(session, config).bulk_set_category(
        body.get("lesson_ids") or [], body.get("category", "system_issue")
    )
    session.commit()
    return {"status": "ok", "updated": n}


@router.post("/memory/lesson/{lesson_id}/category")
def memory_lesson_category(
    lesson_id: int, body: dict, session: Session = Depends(get_session)
):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService

    config = ConfigManager(session).get_current()
    row = LessonMemoryService(session, config).set_category(
        lesson_id, body.get("category"), body.get("memory_type")
    )
    session.commit()
    return {"status": "ok" if row else "error", "lesson_id": lesson_id}


@router.get("/decisions/latest")
def decisions_latest(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.decisions_service import latest_summary

    return latest_summary(session, cycle_run_id)


@router.get("/decisions/approved")
def decisions_approved(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.decisions_service import approved_decisions

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = approved_decisions(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "decisions": rows}


@router.get("/decisions/blocked")
def decisions_blocked(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.decisions_service import blocked_decisions

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = blocked_decisions(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "decisions": rows}


@router.get("/decisions/deferred")
def decisions_deferred(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.decisions_service import deferred_decisions

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = deferred_decisions(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "decisions": rows}


@router.get("/decisions/orders")
def decisions_orders(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.decisions_service import orders_decisions

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = orders_decisions(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "orders": rows}


@router.get("/decisions/lessons")
def decisions_lessons(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    from app.services.decisions_service import lessons_decisions

    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = lessons_decisions(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "lessons": rows}


@router.get("/positions/state")
def positions_state(session: Session = Depends(get_session)):
    from app.services.positions_tab_service import position_states

    rows = position_states(session)
    return {"status": "ok", "count": len(rows), "states": rows}


@router.post("/positions/state/backfill")
def positions_state_backfill(session: Session = Depends(get_session)):
    from app.services.position_state_service import backfill_position_states

    out = backfill_position_states(session)
    session.commit()
    return out


@router.get("/trades/history")
def trades_history(limit: int = 50, session: Session = Depends(get_session)):
    from app.services.positions_tab_service import trades_history as th

    rows = th(session, limit=limit)
    return {"status": "ok", "count": len(rows), "trades": rows}


@router.post("/positions/refresh")
def positions_refresh(session: Session = Depends(get_session)):
    from app.services.positions_tab_service import refresh_positions

    return refresh_positions(session)


@router.post("/positions/monitor/run")
def positions_monitor_run(session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.memory_cycle_processor import process_cycle_memories
    from app.services.query_service import resolve_cycle_run_id

    config = ConfigManager(session).get_current()
    cid = resolve_cycle_run_id(session, "latest") or "manual-monitor"
    ids = process_cycle_memories(session, config, cid)
    session.commit()
    return {"status": "ok", "cycle_run_id": cid, "memories_touched": len(ids)}


@router.post("/positions/{symbol}/manual-exit-request")
def positions_manual_exit(symbol: str, session: Session = Depends(get_session)):
    from app.services.paper_execution_service import PaperExecutionService

    return {
        "status": "pending",
        "message": "Manual exit must pass paper preflight — use execution panel or POST /execution/paper/run-selected for exits when implemented",
        "symbol": symbol,
        "paper_only": True,
        "live_locked": True,
        **PaperExecutionService(session).status(),
    }


@router.post("/memory/backfill")
def memory_backfill(cycle_run_id: str = "8796825e-5f25-4cfa-b0f9-b0141f61859c", session: Session = Depends(get_session)):
    from app.services.memory_cycle_processor import backfill_doge_cycle_if_present

    count = backfill_doge_cycle_if_present(session, cycle_run_id)
    return {"status": "ok", "lessons_updated": count, "cycle_run_id": cycle_run_id}


@router.get("/ai/config-proposals")
def ai_config_proposals(session: Session = Depends(get_session)):
    from sqlmodel import select
    from app.database import AIConfigProposal

    rows = session.exec(select(AIConfigProposal).order_by(AIConfigProposal.created_at.desc()).limit(50)).all()
    return {
        "status": "ok",
        "count": len(rows),
        "proposals": [
            {
                "id": r.id,
                "cycle_run_id": r.cycle_run_id,
                "proposed_by": r.proposed_by,
                "config_patch": r.config_patch,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/ai/reviews")
def get_ai_reviews(cycle_run_id: str = "latest", session: Session = Depends(get_session)):
    cid = resolve_cycle_run_id(session, cycle_run_id)
    rows = reviews_for_cycle(session, cycle_run_id)
    return {"status": "ok", "cycle_run_id": cid, "count": len(rows), "reviews": rows}


@router.post("/ai/review")
def trigger_ai_review_legacy(session: Session = Depends(get_session)):
    return _run_ai_review(session, cycle_run_id=None, mode="quick", force=False)


@router.post("/ai/review/run")
def run_ai_review(
    cycle_run_id: str = "latest",
    mode: str = "quick",
    force: bool = False,
    session: Session = Depends(get_session),
):
    return _run_ai_review(session, cycle_run_id=cycle_run_id, mode=mode, force=force)


def _run_ai_review(session: Session, cycle_run_id: str | None, mode: str, force: bool):
    from app.database import SystemHealth
    from app.services.cycle_persistence import latest_cycle_end

    ai = AIFundManager(session)
    if not ai.configured:
        return {"status": "error", "message": "Gemini not configured or AI disabled", "meta": {}}

    cid = resolve_cycle_run_id(session, cycle_run_id or "latest")
    log = latest_cycle_end(session)
    summary = (log.details if log else None) or {}
    if not summary and session.get(SystemHealth, 1):
        summary = (session.get(SystemHealth, 1).details or {}).get("last_cycle", {})

    ctx = build_compact_cycle_context(session, cid or "", summary) if cid else build_dashboard(session)
    review, meta = ai.review(
        "manual_review",
        ctx if isinstance(ctx, dict) else {"dashboard": "compact"},
        subject_id=cid,
        cycle_run_id=cid,
        mode=mode,
        force=force,
    )
    if review is None and meta.get("ai_review_status") not in ("success",):
        return {
            "status": "skipped" if "skipped" in str(meta.get("ai_review_status", "")) else "error",
            "message": meta.get("ai_review_error_message"),
            "meta": meta,
        }
    return {
        "status": "ok",
        "review": {
            "id": review.id,
            "decision": review.decision,
            "summary": review.summary,
            "review_status": review.review_status,
        }
        if review
        else None,
        "meta": meta,
    }


@router.get("/memory/symbols")
def get_symbol_memory(session: Session = Depends(get_session)):
    from sqlmodel import select
    from app.database import SymbolMemory

    sym_rows = session.exec(select(SymbolMemory).order_by(SymbolMemory.updated_at.desc()).limit(50)).all()
    return {
        "status": "ok",
        "symbol_memories": [
            {
                "id": r.id,
                "symbol": r.symbol,
                "memory_key": r.memory_key,
                "lesson": r.lesson,
                "strength": r.strength,
                "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else None,
            }
            for r in sym_rows
        ],
    }


@router.get("/lab/status")
def lab_status(session: Session = Depends(get_session)):
    ResearchLabService(session).ensure_library()
    return ResearchLabService(session).status()


@router.post("/lab/research/run")
def lab_research_run(body: dict = Body(default={}), session: Session = Depends(get_session)):
    return ResearchLabService(session).run_research_batch(body)


@router.post("/lab/backtest/run")
def lab_backtest_run(
    body: dict = Body(default={}),
    symbol: str | None = None,
    session: Session = Depends(get_session),
):
    if symbol and not body.get("symbols"):
        body = {**body, "symbols": [symbol], "strategy_id": body.get("strategy_id", "crypto_push_pull")}
    if not body:
        return LabService(session).run_crypto_backtest(symbol or "BTC/USD")
    return ResearchLabService(session).run_backtest(body)


@router.post("/lab/backtest/batch-run")
def lab_backtest_batch(body: dict = Body(default={}), session: Session = Depends(get_session)):
    return ResearchLabService(session).batch_backtest(body)


@router.get("/lab/backtest/runs")
def lab_backtest_runs(limit: int = 50, session: Session = Depends(get_session)):
    from app.services.research_backtest_engine import ResearchBacktestEngine
    from app.services.config_manager import ConfigManager

    cfg = ConfigManager(session).get_current()
    runs = ResearchBacktestEngine(session, cfg).list_runs(limit)
    legacy = LabService(session).list_backtests(min(limit, 20))
    return {"status": "ok", "runs": runs, "legacy_runs": legacy}


@router.get("/lab/backtest/result/{run_id}")
def lab_backtest_result(run_id: str, session: Session = Depends(get_session)):
    result = ResearchLabService(session).get_backtest_result(run_id)
    if not result:
        return {"status": "error", "message": "Run not found"}
    return {"status": "ok", "result": result}


@router.get("/lab/experiments")
def lab_experiments(session: Session = Depends(get_session)):
    return {"status": "ok", **ResearchLabService(session).list_experiments()}


@router.get("/lab/strategy-candidates")
def lab_strategy_candidates(session: Session = Depends(get_session)):
    return {"status": "ok", "candidates": ResearchLabService(session).list_candidates()}


@router.get("/lab/research-memories")
def lab_research_memories(limit: int = 50, session: Session = Depends(get_session)):
    return {"status": "ok", "memories": ResearchLabService(session).research_memories(limit)}


@router.get("/lab/rejected-strategies")
def lab_rejected(session: Session = Depends(get_session)):
    return {"status": "ok", "rejected": ResearchLabService(session).rejected_strategies()}


@router.get("/lab/promising-strategies")
def lab_promising(session: Session = Depends(get_session)):
    return {"status": "ok", "promising": ResearchLabService(session).promising_strategies()}


@router.get("/lab/leaderboard")
@router.get("/lab/strategy-leaderboard")
def lab_leaderboard(session: Session = Depends(get_session)):
    return {"status": "ok", "leaderboard": ResearchLabService(session).leaderboard()}


@router.post("/lab/strategies/seed")
def lab_strategies_seed(session: Session = Depends(get_session)):
    n = ResearchLabService(session).ensure_library()
    from app.services.strategy_library import seed_strategy_library

    count = seed_strategy_library(session, force_update=True)
    session.commit()
    return {"status": "ok", "seeded": count, "total": n}


@router.get("/lab/strategy-definitions")
def lab_strategy_definitions(session: Session = Depends(get_session)):
    from app.services.strategy_library import list_strategies

    ResearchLabService(session).ensure_library()
    return {"status": "ok", "strategies": list_strategies(session)}


@router.post("/lab/data/fetch")
def lab_data_fetch(body: dict = Body(default={}), session: Session = Depends(get_session)):
    out = ResearchLabService(session).fetch_historical_data(body)
    session.commit()
    return out


@router.get("/lab/historical-coverage")
def lab_historical_coverage(session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager

    cfg = ConfigManager(session).get_current()
    return {"status": "ok", "coverage": HistoricalDataService(session, cfg).list_coverage()}


@router.post("/lab/walk-forward/run")
def lab_walk_forward(body: dict = Body(default={}), session: Session = Depends(get_session)):
    return ResearchLabService(session).run_walk_forward(body)


@router.post("/lab/strategy/{strategy_id}/promote-to-paper-candidate")
def lab_promote(strategy_id: str, body: dict = Body(default={}), session: Session = Depends(get_session)):
    return ResearchLabService(session).promote_to_paper_candidate(strategy_id, body)


@router.post("/lab/strategy/{strategy_id}/reject")
def lab_reject_strategy(strategy_id: str, body: dict = Body(default={}), session: Session = Depends(get_session)):
    return ResearchLabService(session).reject_strategy(strategy_id, body)


@router.get("/lab/strategies")
def lab_strategies(session: Session = Depends(get_session)):
    ResearchLabService(session).ensure_library()
    return {"status": "ok", "strategies": list_strategies(session)}


@router.get("/lab/strategy-notes")
def lab_strategy_notes(limit: int = 50, session: Session = Depends(get_session)):
    return {"status": "ok", "notes": LabService(session).list_strategy_notes(limit)}


@router.get("/lab/memory")
def lab_memory(limit: int = 50, session: Session = Depends(get_session)):
    return {"status": "ok", "memories": ResearchLabService(session).research_memories(limit)}


@router.post("/memory/import/legacy-ai-bundle")
def memory_import_legacy(body: dict = Body(default={}), session: Session = Depends(get_session)):
    out = ResearchLabService(session).import_legacy_bundle(body)
    session.commit()
    return out


@router.post("/memory/reclassify/system-bugs")
def memory_reclassify_system_bugs(session: Session = Depends(get_session)):
    from app.services.config_manager import ConfigManager
    from app.services.lesson_memory_service import LessonMemoryService
    from app.services.memory_categories import CATEGORY_SYSTEM, SYSTEM_TYPES
    from app.database import LessonNode
    from sqlmodel import select

    config = ConfigManager(session).get_current()
    svc = LessonMemoryService(session, config)
    rows = session.exec(select(LessonNode)).all()
    n = 0
    for r in rows:
        if r.memory_type in SYSTEM_TYPES or "bug" in (r.memory_type or "") or "reconciliation" in (r.title or "").lower():
            svc.set_category(r.id, CATEGORY_SYSTEM)
            svc.set_visibility(r.id, visible_to_ai=False, visible_in_graph=False, can_influence_ranking=False)
            n += 1
    session.commit()
    return {"status": "ok", "reclassified": n}


@router.post("/sync/alpaca")
def sync_alpaca(session: Session = Depends(get_session)):
    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"status": "error", "message": "Alpaca not configured"}
    account = adapter.sync_account()
    positions = adapter.sync_positions()
    return {
        "status": "ok" if account else "error",
        "account_synced": account is not None,
        "positions_count": len(positions),
    }


@router.get("/diagnostic-bundle")
def get_diagnostic_bundle(session: Session = Depends(get_session)):
    return export_diagnostic_bundle(session)


@router.get("/diagnostic-bundle/download")
def download_diagnostic_bundle(session: Session = Depends(get_session)):
    data = bundle_as_zip_bytes(session)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=hive-diagnostic-bundle.zip"},
    )
