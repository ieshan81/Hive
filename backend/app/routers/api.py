from fastapi import APIRouter, Depends
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
    from sqlmodel import select
    from app.database import OrderRecord

    cid = resolve_cycle_run_id(session, cycle_run_id)
    q = select(OrderRecord).order_by(OrderRecord.submitted_at.desc()).limit(min(limit, 100))
    rows = session.exec(q).all()
    if cid:
        rows = [r for r in rows if r.cycle_run_id == cid or r.cycle_run_id is None]
    return {
        "status": "ok",
        "cycle_run_id": cid,
        "count": len(rows),
        "orders": [
            {
                "id": r.id,
                "alpaca_order_id": r.alpaca_order_id,
                "client_order_id": r.broker_client_order_id,
                "symbol": r.symbol,
                "side": r.side,
                "qty": r.qty,
                "order_type": r.order_type,
                "status": r.status,
                "limit_price": (r.raw_payload or {}).get("limit_price"),
                "filled_avg_price": r.filled_avg_price,
                "submitted_at": r.submitted_at.isoformat() + "Z" if r.submitted_at else None,
                "cycle_run_id": r.cycle_run_id,
                "signal_id": r.signal_id,
            }
            for r in rows
        ],
    }


@router.get("/positions")
def get_positions(session: Session = Depends(get_session)):
    from sqlmodel import select
    from app.database import PositionSnapshot

    rows = session.exec(select(PositionSnapshot).order_by(PositionSnapshot.synced_at.desc())).all()
    seen = set()
    out = []
    for p in rows:
        if p.symbol in seen:
            continue
        seen.add(p.symbol)
        if (p.qty or 0) <= 0:
            continue
        out.append(
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "side": p.side,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "unrealized_pl": p.unrealized_pl,
                "unrealized_pl_pct": p.unrealized_pl_pct,
                "synced_at": p.synced_at.isoformat() + "Z" if p.synced_at else None,
            }
        )
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
    return LabService(session).status()


@router.post("/lab/backtest/run")
def lab_backtest_run(symbol: str = "BTC/USD", session: Session = Depends(get_session)):
    return LabService(session).run_crypto_backtest(symbol)


@router.get("/lab/backtest/runs")
def lab_backtest_runs(limit: int = 20, session: Session = Depends(get_session)):
    return {"status": "ok", "runs": LabService(session).list_backtests(limit)}


@router.get("/lab/strategy-notes")
def lab_strategy_notes(limit: int = 50, session: Session = Depends(get_session)):
    return {"status": "ok", "notes": LabService(session).list_strategy_notes(limit)}


@router.get("/lab/memory")
def lab_memory(limit: int = 50, session: Session = Depends(get_session)):
    return {"status": "ok", "memories": LabService(session).list_memory(limit)}


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
