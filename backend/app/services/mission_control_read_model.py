"""Canonical Mission Control read model.

READ ONLY: this module must not fetch provider data, score the universe,
call Gemini, submit orders, or mutate DB state. It only summarizes the last
known persisted/cache-safe truth for dashboard rendering.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Callable

from sqlmodel import Session, func, select

from app.config import settings
from app.database import (
    AccountSnapshot,
    DiagnosticExportJob,
    ExecutionLog,
    HistoricalBar,
    LessonNode,
    OrderRecord,
    PaperExperimentDecision,
    PositionSnapshot,
    SettingsActionAudit,
    SystemHealth,
    SymbolCandidate,
)
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.env_pause_service import env_pause_status
from app.services.kill_switch_service import KillSwitchService
from app.services.paper_learning_blockers import friendly_blocker


SCHEMA_VERSION = "mission_control_read_model.v1"


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _iso(value: Any) -> str | None:
    return value.isoformat() + "Z" if hasattr(value, "isoformat") else None


def _age_seconds(value: datetime | None) -> int | None:
    if not value:
        return None
    return max(0, int((datetime.utcnow() - value).total_seconds()))


def _safe(section: str, warnings: list[str], fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        out = fn()
        if not isinstance(out, dict):
            raise TypeError(f"{section} returned {type(out).__name__}")
        return out
    except Exception as exc:
        warnings.append(f"{section}: {type(exc).__name__}")
        return {"status": "degraded", "error": str(exc)[:220]}


def _latest_audit(session: Session, action: str) -> SettingsActionAudit | None:
    return session.exec(
        select(SettingsActionAudit)
        .where(SettingsActionAudit.action == action)
        .order_by(SettingsActionAudit.created_at.desc())
    ).first()


def _latest_account(session: Session) -> AccountSnapshot | None:
    return session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()


def _symbol_key(value: Any) -> str:
    return str(value or "").upper().replace("/", "").replace("-", "").strip()


def _candidate_score(row: dict[str, Any]) -> float:
    for key in (
        "trade_quality_score",
        "universe_rank_score",
        "quality_score",
        "push_score",
        "ranking_score",
    ):
        try:
            if row.get(key) is not None:
                return float(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _dedupe_symbol_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    duplicate_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        key = _symbol_key(row.get("symbol"))
        duplicate_counts[key] = duplicate_counts.get(key, 0) + 1
        existing = by_symbol.get(key)
        if not existing:
            by_symbol[key] = dict(row)
            continue
        existing_score = _candidate_score(existing)
        new_score = _candidate_score(row)
        existing_time = str(existing.get("scanned_at") or existing.get("created_at") or "")
        new_time = str(row.get("scanned_at") or row.get("created_at") or "")
        if new_score > existing_score or (new_score == existing_score and new_time > existing_time):
            by_symbol[key] = dict(row)
    out: list[dict[str, Any]] = []
    for row in by_symbol.values():
        key = _symbol_key(row.get("symbol"))
        count = duplicate_counts.get(key, 1)
        if count > 1:
            row["duplicate_candidates_collapsed"] = count
        out.append(row)
    return sorted(out, key=_candidate_score, reverse=True)


def _account_summary(session: Session) -> dict[str, Any]:
    account = _latest_account(session)
    positions = list(
        session.exec(
            select(PositionSnapshot)
            .where(PositionSnapshot.qty > 0)
            .order_by(PositionSnapshot.synced_at.desc())
            .limit(100)
        ).all()
    )
    open_pl = sum(float(p.unrealized_pl or 0.0) for p in positions)
    last_position_sync = max((p.synced_at for p in positions if p.synced_at), default=None)
    if not account:
        return {
            "status": "degraded" if settings.alpaca_configured else "not_configured",
            "alpaca_configured": settings.alpaca_configured,
            "alpaca_connected": False,
            "connected": False,
            "equity": None,
            "cash": None,
            "buying_power": None,
            "open_pl": open_pl,
            "open_positions_count": len(positions),
            "last_sync_at": _iso(last_position_sync),
            "snapshot_age_seconds": _age_seconds(last_position_sync),
            "message": "No account snapshot has been synced yet.",
        }
    return {
        "status": "ok",
        "alpaca_configured": settings.alpaca_configured,
        "alpaca_connected": True,
        "connected": True,
        "equity": account.equity,
        "cash": account.cash,
        "buying_power": account.buying_power,
        "portfolio_value": account.portfolio_value,
        "daily_pl": account.daily_pl,
        "daily_pl_pct": account.daily_pl_pct,
        "drawdown_pct": account.drawdown_pct,
        "open_pl": open_pl,
        "open_positions_count": len(positions),
        "last_sync_at": _iso(account.synced_at),
        "position_sync_at": _iso(last_position_sync),
        "snapshot_age_seconds": _age_seconds(account.synced_at),
        "broker_sync_status": "synced" if account.synced_at else "missing",
    }


def _execution_safety(session: Session, cfg: dict) -> dict[str, Any]:
    env = env_pause_status()
    live = live_lock_status(cfg)
    kill = KillSwitchService(session, cfg).status()
    paper_broker = is_paper_broker_url()
    paper_orders_enabled = bool(cfg_get(cfg, "execution.paper_orders_enabled", False))
    live_orders_enabled = bool(cfg_get(cfg, "execution.live_orders_enabled", False)) or bool(
        cfg.get("live_trading_enabled", False)
    )
    learning_cfg = dict(cfg.get("autonomous_paper_learning") or {})
    paper_learning_on = bool(learning_cfg.get("mode_enabled"))
    scheduler_enabled = bool(learning_cfg.get("scheduler_enabled"))
    open_positions_count = int(
        session.exec(select(func.count()).select_from(PositionSnapshot).where(PositionSnapshot.qty > 0)).one() or 0
    )
    active_order_statuses = ["pending", "submitted", "accepted", "new", "partially_filled"]
    active_orders_count = int(
        session.exec(
            select(func.count()).select_from(OrderRecord).where(OrderRecord.status.in_(active_order_statuses))
        ).one()
        or 0
    )
    blockers: list[str] = []
    if not paper_broker:
        blockers.append("broker_not_paper")
    if live.get("live_lock_status") != "locked":
        blockers.append("live_lock_not_locked")
    if live_orders_enabled:
        blockers.append("live_trading_flag_set")
    if not paper_orders_enabled:
        blockers.append("paper_execution_off")
    if not paper_learning_on:
        blockers.append("paper_learning_off")
    if not scheduler_enabled:
        blockers.append("scheduler_off")
    if env.get("paper_trading_paused_by_env"):
        blockers.append("env_pause_paper_trading")
    if env.get("autonomous_learning_paused_by_env"):
        blockers.append("env_pause_learning")
    if not bool(kill.get("entries_allowed")):
        blockers.append("kill_switch_active")
    can_place = (
        paper_broker
        and live.get("live_lock_status") == "locked"
        and paper_orders_enabled
        and paper_learning_on
        and not live_orders_enabled
        and not env.get("any_env_pause")
        and bool(kill.get("entries_allowed"))
    )
    plain_blockers = [friendly_blocker(b) for b in blockers if b != "kill_switch_active"]
    if not bool(kill.get("entries_allowed")):
        switches = kill.get("active_switches") or []
        message = None
        if switches and isinstance(switches[0], dict):
            message = switches[0].get("message")
        plain_blockers.insert(0, str(message or "Paper entries are blocked by the kill switch."))
    switches = kill.get("active_switches") or []
    drawdown_blocker = next(
        (
            s
            for s in switches
            if isinstance(s, dict) and str(s.get("switch_name") or "").lower() in {"daily_drawdown", "max_drawdown"}
        ),
        None,
    )
    next_action = (
        "Wait for drawdown window reset or intentionally change risk config."
        if drawdown_blocker
        else plain_blockers[0]
        if plain_blockers
        else "Paper entries may submit when a candidate passes the cage."
    )
    return {
        "status": "ok" if not blockers else "blocked",
        "paper_broker": paper_broker,
        "paper_broker_connected": paper_broker,
        "broker_mode": "paper" if paper_broker else "unknown",
        "live_lock_status": live.get("live_lock_status"),
        "live_trading_locked": live.get("live_lock_status") == "locked",
        "live_orders_enabled": live_orders_enabled,
        "paper_orders_enabled": paper_orders_enabled,
        "paper_learning_on": paper_learning_on,
        "scheduler_enabled": scheduler_enabled,
        "can_place_paper_orders_now": can_place,
        "bot_can_submit_paper_entries_now": can_place,
        "kill_switch_active": not bool(kill.get("entries_allowed")),
        "drawdown_blocker": drawdown_blocker,
        "open_positions_count": open_positions_count,
        "active_orders_count": active_orders_count,
        "next_action": next_action,
        "blocker_codes": blockers,
        "blockers": plain_blockers,
        "kill_switch": kill,
    }


def _latest_tick_details(session: Session) -> tuple[SettingsActionAudit | None, dict[str, Any]]:
    row = _latest_audit(session, "autonomous_run_one_cycle")
    return row, dict(row.details_json or {}) if row and row.details_json else {}


def _universe_summary(session: Session) -> dict[str, Any]:
    tick, details = _latest_tick_details(session)
    latest_candidate = session.exec(
        select(SymbolCandidate).order_by(SymbolCandidate.scanned_at.desc()).limit(1)
    ).first()
    symbol_count = session.exec(select(func.count()).select_from(SymbolCandidate)).one()
    cached_bar_symbols = session.exec(select(func.count(func.distinct(HistoricalBar.symbol)))).one()
    reason_breakdown = (
        details.get("no_trade_reason_breakdown")
        or details.get("reason_breakdown")
        or details.get("block_breakdown")
        or {}
    )
    top_candidates = []
    for key in ("selected_candidate", "top_candidate"):
        row = details.get(key)
        if isinstance(row, dict) and row.get("symbol"):
            top_candidates.append(row)
    for row in details.get("push_pull_scores") or []:
        if isinstance(row, dict) and row.get("symbol"):
            top_candidates.append(row)
        if len(top_candidates) >= 5:
            break
    if not top_candidates:
        rows = list(
            session.exec(
                select(SymbolCandidate)
                .order_by(SymbolCandidate.scanned_at.desc())
                .limit(5)
            ).all()
        )
        top_candidates = [
            {
                "symbol": r.symbol,
                "asset_class": r.asset_class,
                "eligibility": r.eligibility,
                "spread_pct": r.spread_pct,
                "scanned_at": _iso(r.scanned_at),
            }
            for r in rows
        ]
    top_candidates = _dedupe_symbol_rows(top_candidates)

    available = int(details.get("symbols_scanned_count") or symbol_count or 0)
    fresh = int(details.get("fresh_bar_count") or 0)
    eligible = int(details.get("approved_count") or details.get("eligible_strategy_count") or 0)
    scored = int(
        details.get("candidates_created")
        or len(details.get("push_pull_scores") or [])
        or details.get("symbols_scanned_count")
        or 0
    )
    shortlist = int(details.get("order_count") or details.get("orders_created") or eligible or 0)
    top_blockers = [
        {"code": str(code), "count": int(count), "label": str(code).replace("_", " ")}
        for code, count in Counter(reason_breakdown).most_common(8)
        if int(count or 0) > 0
    ]
    last_scan = tick.created_at if tick else latest_candidate.scanned_at if latest_candidate else None
    stale_reason = None
    if not last_scan:
        stale_reason = "No persisted universe scan/tick result yet."
    elif _age_seconds(last_scan) and _age_seconds(last_scan) > 900:
        stale_reason = "Last scan is older than 15 minutes."
    elif shortlist == 0 and top_blockers:
        stale_reason = "No shortlist because latest scan blockers dominate."
    return {
        "status": "ok" if last_scan else "empty",
        "last_scan_at": _iso(last_scan),
        "snapshot_age_seconds": _age_seconds(last_scan),
        "funnel": {
            "available": available,
            "cached": int(cached_bar_symbols or available or 0),
            "fresh": fresh,
            "scored": scored,
            "eligible": eligible,
            "shortlisted": shortlist,
        },
        "top_blockers": top_blockers,
        "top_candidates": top_candidates[:8],
        "stale_reason": stale_reason,
        "next_required_action": "Run universe scan" if not last_scan else "Run agent cycle" if shortlist == 0 else "Monitor paper execution",
    }


def _push_pull_summary(session: Session) -> dict[str, Any]:
    tick, details = _latest_tick_details(session)
    top = details.get("selected_candidate") or details.get("top_candidate")
    rejected = details.get("rejected_candidates") or []
    reason_breakdown = details.get("no_trade_reason_breakdown") or details.get("reason_breakdown") or {}
    top_rejected_reason = None
    if isinstance(rejected, list) and rejected:
        top_rejected_reason = (rejected[0] or {}).get("no_trade_reason") or (rejected[0] or {}).get("reason")
    if not top_rejected_reason and reason_breakdown:
        top_rejected_reason = max(reason_breakdown.items(), key=lambda kv: int(kv[1] or 0))[0]
    data_stale = any(k in reason_breakdown for k in ("data_stale", "stale_bar", "stale_quote"))
    return {
        "status": "ok" if tick else "not_run",
        "last_tick_at": _iso(tick.created_at if tick else None),
        "last_result": details.get("result") or details.get("reason") or ("not_run" if not tick else "unknown"),
        "plain_summary": details.get("plain_summary"),
        "top_candidate": top if isinstance(top, dict) else None,
        "top_rejected_reason": top_rejected_reason,
        "data_stale": data_stale,
        "reason_breakdown": reason_breakdown,
        "next_refresh_needed": bool(data_stale or not tick),
    }


def _memory_summary(session: Session) -> dict[str, Any]:
    active = session.exec(
        select(func.count()).select_from(LessonNode).where(LessonNode.status == "active")
    ).one()
    validated = session.exec(
        select(func.count())
        .select_from(LessonNode)
        .where(LessonNode.status == "active", LessonNode.system_validation_status.in_(["validated", "passed"]))
    ).one()
    consolidated = session.exec(
        select(func.count()).select_from(LessonNode).where(LessonNode.is_consolidated == True)  # noqa: E712
    ).one()
    latest = session.exec(
        select(LessonNode).order_by(LessonNode.updated_at.desc()).limit(1)
    ).first()
    return {
        "status": "ok",
        "active_lessons": int(active or 0),
        "validated_lessons": int(validated or 0),
        "consolidated_lessons": int(consolidated or 0),
        "latest_lesson": {
            "id": latest.id,
            "title": latest.title,
            "summary": latest.summary,
            "symbol": latest.symbol,
            "updated_at": _iso(latest.updated_at),
        }
        if latest
        else None,
        "health": "empty" if not active else "ok",
    }


def _diagnostic_summary(session: Session) -> dict[str, Any]:
    running = session.exec(
        select(DiagnosticExportJob)
        .where(DiagnosticExportJob.status.in_(["queued", "running"]))
        .order_by(DiagnosticExportJob.started_at.desc())
    ).first()
    last = session.exec(
        select(DiagnosticExportJob)
        .where(DiagnosticExportJob.status == "complete")
        .order_by(DiagnosticExportJob.completed_at.desc())
    ).first()
    failed = session.exec(
        select(DiagnosticExportJob)
        .where(DiagnosticExportJob.status == "failed")
        .order_by(DiagnosticExportJob.completed_at.desc())
    ).first()
    return {
        "status": "running" if running else "ok" if last else "not_run",
        "export_in_progress": bool(running),
        "current_job": _job_public(running) if running else None,
        "last_completed": _job_public(last) if last else None,
        "last_failed": _job_public(failed) if failed else None,
    }


def _job_public(row: DiagnosticExportJob | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "job_id": row.job_id,
        "status": row.status,
        "progress_pct": row.progress_pct,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "filename": row.filename,
        "file_count": row.file_count,
        "failed_sections": row.failed_sections or [],
        "error": row.error,
        "download_available": bool(row.zip_bytes or row.storage_path),
        "zip_size_bytes": row.zip_size_bytes,
    }


def _worker_summary(session: Session) -> dict[str, Any]:
    tick, details = _latest_tick_details(session)
    scheduler_row = _latest_audit(session, "autonomous_scheduler")
    scheduler = dict(scheduler_row.details_json or {}) if scheduler_row and scheduler_row.details_json else {}
    return {
        "status": "ok",
        "scheduler_enabled": bool(scheduler.get("enabled") or scheduler.get("scheduler_enabled")),
        "scheduler_paused": bool(scheduler.get("paused")),
        "last_tick_at": _iso(tick.created_at if tick else None),
        "last_tick_result": details.get("result") or details.get("reason"),
        "last_tick_orders_created": int(details.get("orders_created") or details.get("order_count") or 0),
    }


def _latest_order_summary(session: Session) -> dict[str, Any]:
    latest_order = session.exec(select(OrderRecord).order_by(OrderRecord.submitted_at.desc()).limit(1)).first()
    latest_exec = session.exec(select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(1)).first()
    latest_decision = session.exec(
        select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(1)
    ).first()
    return {
        "latest_order": {
            "id": latest_order.id,
            "symbol": latest_order.symbol,
            "side": latest_order.side,
            "status": latest_order.status,
            "submitted_at": _iso(latest_order.submitted_at),
        }
        if latest_order
        else None,
        "latest_execution_log": {
            "event_id": latest_exec.event_id,
            "symbol": latest_exec.symbol,
            "side": latest_exec.side,
            "status": latest_exec.status,
            "created_at": _iso(latest_exec.created_at),
            "reject_reason": latest_exec.reject_reason,
        }
        if latest_exec
        else None,
        "latest_decision": {
            "id": latest_decision.id,
            "symbol": latest_decision.symbol,
            "decision": latest_decision.decision,
            "reason_code": latest_decision.reason_code,
            "execution_status": latest_decision.execution_status,
            "created_at": _iso(latest_decision.created_at),
        }
        if latest_decision
        else None,
    }


def _positions_payload(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.exec(
            select(PositionSnapshot)
            .where(PositionSnapshot.qty > 0)
            .order_by(PositionSnapshot.synced_at.desc())
            .limit(50)
        ).all()
    )
    return [
        {
            "symbol": p.symbol,
            "qty": p.qty,
            "side": p.side,
            "market_value": p.market_value,
            "unrealized_pl": p.unrealized_pl,
            "unrealized_pl_pct": p.unrealized_pl_pct,
            "current_price": p.current_price,
            "avg_entry_price": p.avg_entry_price,
        }
        for p in rows
    ]


def _recent_trades_payload(session: Session) -> list[dict[str, Any]]:
    rows = list(session.exec(select(OrderRecord).order_by(OrderRecord.submitted_at.desc()).limit(8)).all())
    return [
        {
            "symbol": r.symbol,
            "side": r.side,
            "status": r.status,
            "quantity": r.qty,
            "submitted_at": _iso(r.submitted_at),
        }
        for r in rows
    ]


def build_mission_control_status(session: Session) -> dict[str, Any]:
    """Build the canonical fast dashboard payload from persisted state only."""

    warnings: list[str] = []
    cfg = _safe("config", warnings, lambda: {"config": ConfigManager(session).get_current()}).get("config") or {}
    generated = _now()
    account = _safe("account", warnings, lambda: _account_summary(session))
    execution = _safe("execution_safety", warnings, lambda: _execution_safety(session, cfg))
    universe = _safe("universe", warnings, lambda: _universe_summary(session))
    push_pull = _safe("push_pull", warnings, lambda: _push_pull_summary(session))
    memory = _safe("memory", warnings, lambda: _memory_summary(session))
    diagnostics = _safe("diagnostics", warnings, lambda: _diagnostic_summary(session))
    worker = _safe("worker", warnings, lambda: _worker_summary(session))
    research_os = _safe(
        "research_os",
        warnings,
        lambda: __import__(
            "app.services.research_os_service",
            fromlist=["ResearchOSReadService"],
        ).ResearchOSReadService(session).status(),
    )
    alpha_factory = _safe(
        "alpha_factory",
        warnings,
        lambda: __import__(
            "app.services.alpha_research_read_model_service",
            fromlist=["AlphaResearchReadModelService"],
        ).AlphaResearchReadModelService(session, cfg).status(),
    )
    latest_order = _safe("latest_order", warnings, lambda: _latest_order_summary(session))
    positions = _safe("positions", warnings, lambda: {"items": _positions_payload(session)}).get("items") or []
    recent_trades = _safe("recent_trades", warnings, lambda: {"items": _recent_trades_payload(session)}).get("items") or []
    health = session.get(SystemHealth, 1)
    ages = [
        account.get("snapshot_age_seconds"),
        universe.get("snapshot_age_seconds"),
    ]
    max_age = max([int(a) for a in ages if isinstance(a, int)], default=None)
    stale = bool(max_age is not None and max_age > 900)
    degraded = bool(warnings or account.get("status") == "degraded" or execution.get("status") == "blocked")
    top_blockers = universe.get("top_blockers") or []
    next_action = "Run agent cycle"
    if not account.get("alpaca_connected"):
        next_action = "Sync broker account"
    elif universe.get("status") == "empty":
        next_action = "Run universe scan"
    elif execution.get("blockers"):
        next_action = str(execution.get("blockers")[0])
    elif push_pull.get("next_refresh_needed"):
        next_action = "Refresh market data, then run agent cycle"
    universe_funnel = universe.get("funnel") or {}
    top_candidates = universe.get("top_candidates") or []
    eligible_candidates = (
        top_candidates
        if int(universe_funnel.get("eligible") or 0) > 0 or int(universe_funnel.get("shortlisted") or 0) > 0
        else []
    )
    block_breakdown = {b.get("code"): b.get("count") for b in universe.get("top_blockers") or [] if b.get("code")}
    cleared_note = ""
    kill_status = execution.get("kill_switch") if isinstance(execution.get("kill_switch"), dict) else {}
    if kill_status.get("state") == "cleared_recently" and isinstance(kill_status.get("last_preflight_block"), dict):
        last_block = kill_status["last_preflight_block"]
        cleared_note = (
            f" Recently blocked by {last_block.get('human_reason') or last_block.get('reject_reason')}; "
            "current kill-switch status is clear."
        )
    cockpit_message = (
        f"Cached product truth: {universe_funnel.get('available', 0)} available, "
        f"{universe_funnel.get('eligible', 0)} eligible, {universe_funnel.get('shortlisted', 0)} shortlisted. "
        f"{next_action}.{cleared_note}"
    )
    return {
        "status": "degraded" if degraded else "ok",
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "live_truth": True,
        "summary": True,
        "alpaca_connected": account.get("alpaca_connected"),
        "freshness": {
            "snapshot_age_seconds": max_age,
            "stale": stale,
            "degraded": degraded,
            "warnings": warnings,
            "system_health_updated_at": _iso(health.updated_at) if health else None,
        },
        "account": account,
        "paper_execution": execution,
        "live_lock": {
            "status": execution.get("live_lock_status"),
            "locked": execution.get("live_trading_locked"),
        },
        "broker_mode": execution.get("broker_mode"),
        "open_positions_summary": {
            "count": account.get("open_positions_count"),
            "open_pl": account.get("open_pl"),
        },
        "latest_order_summary": latest_order,
        "universe": universe,
        "eligible_entries_summary": {
            "count": (universe.get("funnel") or {}).get("eligible", 0),
            "shortlisted": (universe.get("funnel") or {}).get("shortlisted", 0),
            "top_candidates": eligible_candidates,
        },
        "why_no_trade_summary": {
            "top_blockers": top_blockers,
            "plain": universe.get("stale_reason") or push_pull.get("top_rejected_reason") or "No blocker recorded.",
        },
        "push_pull": push_pull,
        "memory": memory,
        "diagnostics": diagnostics,
        "worker": worker,
        "research_os": research_os,
        "alpha_factory": alpha_factory,
        "system_warnings": warnings,
        "next_recommended_operator_action": next_action,
        "operator_actions": [
            {"label": "Refresh market data", "method": "POST", "endpoint": "/api/market-data/refresh-bars"},
            {"label": "Run universe scan", "method": "POST", "endpoint": "/api/universe/refresh"},
            {"label": "Run alpha research cycle", "method": "POST", "endpoint": "/api/alpha-factory/run-cycle"},
            {"label": "Run paper-learning cycle", "method": "POST", "endpoint": "/api/autonomous-paper-learning/run-one-cycle"},
            {"label": "Start diagnostic export", "method": "POST", "endpoint": "/api/diagnostics/export/run"},
        ],
        # Compatibility aliases for older cockpit/front-end cards. These are
        # still read-only and derived from the canonical sections above.
        "control": {
            "can_place_paper_orders": execution.get("can_place_paper_orders_now"),
            "paper_learning_on": execution.get("paper_learning_on"),
            "bot_can_place": execution.get("can_place_paper_orders_now"),
            "blockers": execution.get("blockers") or [],
            "mode": "paper_learning" if execution.get("paper_learning_on") else "watching",
        },
        "funnel": {
            "available": universe_funnel.get("available", 0),
            "cached": universe_funnel.get("cached", 0),
            "fresh": universe_funnel.get("fresh", 0),
            "eligible": universe_funnel.get("eligible", 0),
            "ranked": universe_funnel.get("scored", 0),
            "shortlist": universe_funnel.get("shortlisted", 0),
        },
        "eligible_trades": eligible_candidates,
        "shortlist": eligible_candidates,
        "why_zero_shortlist": universe.get("stale_reason") if not eligible_candidates else None,
        "block_breakdown": block_breakdown,
        "watchlist": {
            "total": universe_funnel.get("available", 0),
            "crypto": {"symbols": [c.get("symbol") for c in top_candidates if "/" in str(c.get("symbol") or "")]},
            "stocks": {"symbols": [c.get("symbol") for c in top_candidates if "/" not in str(c.get("symbol") or "")]},
        },
        "positions": positions,
        "recent_trades": recent_trades,
        "ai_cockpit_message": cockpit_message,
        "ai_brain": {
            "active_lessons": memory.get("active_lessons"),
            "recent_lessons": [memory.get("latest_lesson")] if memory.get("latest_lesson") else [],
        },
    }
