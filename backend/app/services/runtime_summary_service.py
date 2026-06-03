"""Fast runtime truth for global UI header/sidebar — single read-only composition."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.engine_config import cfg_get


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def build_runtime_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    if config is not None:
        cfg = config
    else:
        cfg = _safe(
            lambda: __import__(
                "app.services.config_manager", fromlist=["ConfigManager"]
            ).ConfigManager(session).get_current_readonly(),
            {},
        )

    tiles = _safe(
        lambda: __import__(
            "app.services.mission_control_read_model", fromlist=["build_mission_control_tiles"]
        ).build_mission_control_tiles(session),
        {},
    )
    pe = tiles.get("paper_execution") or {}
    acct = tiles.get("account") or {}
    sched = _safe(
        lambda: __import__(
            "app.services.autonomous_paper_scheduler", fromlist=["AutonomousPaperScheduler"]
        ).AutonomousPaperScheduler(session, cfg).status(),
        {},
    )
    shadow = _safe(
        lambda: __import__(
            "app.services.shadow_league_status_service", fromlist=["build_shadow_league_status"]
        ).build_shadow_league_status(session, cfg),
        {},
    )
    uni = _safe(
        lambda: __import__(
            "app.services.universe_summary_service", fromlist=["build_universe_summary"]
        ).build_universe_summary(session, cfg),
        {},
    )
    paper_status = _safe(
        lambda: __import__(
            "app.services.paper_execution_service", fromlist=["PaperExecutionService"]
        ).PaperExecutionService(session, cfg).status(),
        {},
    )
    alpha = _safe(
        lambda: __import__(
            "app.services.alpha_research_read_model_service", fromlist=["AlphaResearchReadModelService"]
        ).AlphaResearchReadModelService(session, cfg).status(),
        {},
    )

    live = live_lock_status(cfg)
    paper_broker = bool(pe.get("paper_broker") or is_paper_broker_url())
    paper_orders_enabled = bool(pe.get("paper_orders_enabled"))
    paper_entry_ready = bool(paper_status.get("paper_entry_ready"))
    account_synced = bool(
        acct.get("alpaca_connected")
        or acct.get("connected")
        or acct.get("equity") is not None
        or acct.get("last_sync_at")
    )
    broker_connected = bool(paper_broker and account_synced)
    scheduler_enabled = bool(pe.get("scheduler_enabled"))
    paper_candidates = int(alpha.get("paper_candidate_count") or 0)
    blockers = uni.get("blocker_summary") or []
    top_blocker = blockers[0] if blockers else None

    degraded_parts: list[str] = []
    if tiles.get("status") != "ok" and not pe:
        degraded_parts.append("tiles")
    if shadow.get("status") not in ("ok", "disabled", None) and not shadow.get("enabled"):
        degraded_parts.append("shadow")
    if uni.get("status") != "ok":
        degraded_parts.append("universe")

    why_no_trade = None
    if paper_candidates == 0 and top_blocker:
        why_no_trade = str(top_blocker.get("label") or top_blocker.get("code") or "alpha_not_ready")
    elif paper_candidates == 0:
        why_no_trade = "No approved paper candidate yet"

    return {
        "status": "ok",
        "generated_at": _now(),
        "validation_run_id": uni.get("validation_run_id"),
        "live_locked": live.get("live_lock_status") == "locked",
        "live_lock_status": live.get("live_lock_status"),
        "broker_mode": tiles.get("broker_mode") or ("paper" if paper_broker else "unknown"),
        "broker_connected": broker_connected,
        "paper_broker": paper_broker,
        "paper_orders_enabled": paper_orders_enabled,
        "paper_entry_ready": paper_entry_ready,
        "paper_execution_path_ready": paper_entry_ready,
        "paper_trading_enabled": paper_orders_enabled,
        "scheduler_enabled": scheduler_enabled,
        "last_tick_at": sched.get("last_tick_at"),
        "next_tick_at": sched.get("next_planned_at_utc"),
        "shadow_league_enabled": bool(shadow.get("enabled")),
        "shadow_count": int(shadow.get("shadow_league_count") or 0),
        "reason_shadow_count_zero": shadow.get("reason_shadow_count_zero"),
        "shadow_ui_state": shadow.get("ui_state"),
        "scheduler_seen": shadow.get("scheduler_seen"),
        "paper_candidate_count": paper_candidates,
        "current_top_blocker": top_blocker,
        "current_top_blocker_code": (top_blocker or {}).get("code") if isinstance(top_blocker, dict) else None,
        "why_no_trade": why_no_trade,
        "positions_count": int(pe.get("open_positions_count") or acct.get("open_positions_count") or 0),
        "active_orders_count": int(pe.get("active_orders_count") or 0),
        "kill_switch_clear": not bool(pe.get("kill_switch_active")),
        "stock_lane_mode": (uni.get("policy") or {}).get("stock_lane_mode"),
        "stock_entries_allowed": (uni.get("policy") or {}).get("stock_entries_allowed"),
        "funnel_counts": uni.get("funnel_counts"),
        "freshness_counts": uni.get("freshness_counts"),
        "data_degraded": bool(degraded_parts),
        "degraded_reason": ", ".join(degraded_parts) if degraded_parts else None,
        "account_equity": acct.get("equity"),
        "account_last_sync_at": acct.get("last_sync_at"),
        "note": "Fast runtime truth for global UI — prefer over slow /api/mission-control/status for header chips.",
    }
