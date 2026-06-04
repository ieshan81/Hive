"""Fast runtime truth for global UI header/sidebar — single read-only composition."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import ShadowTrade
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.shadow_league_constants import LEVEL_OBSERVED, LEVEL_SHADOW_TRADE
from app.services.shadow_trade_service import shadow_league_enabled


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _recent_tick(last_tick_at: Optional[str], *, max_age_seconds: int = 900) -> bool:
    if not last_tick_at:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last_tick_at).replace("Z", ""))
        return (datetime.utcnow() - last_dt).total_seconds() <= max_age_seconds
    except ValueError:
        return False


def _shadow_runtime(session: Session, cfg: dict, sched: dict[str, Any]) -> dict[str, Any]:
    enabled = shadow_league_enabled(cfg)
    if not enabled:
        return {
            "enabled": False,
            "shadow_league_count": 0,
            "ui_state": "disabled_by_config",
            "reason_shadow_count_zero": "shadow_league_disabled",
        }

    run_id = _safe(
        lambda: __import__(
            "app.services.nuke_epoch_service", fromlist=["get_latest_reset_epoch"]
        ).get_latest_reset_epoch(session).get("validation_run_id"),
        None,
    )
    count = 0
    obs_count = 0
    if run_id:
        count = int(
            session.exec(
                select(func.count())
                .select_from(ShadowTrade)
                .where(
                    ShadowTrade.validation_run_id == run_id,
                    ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
                )
            ).one()
            or 0
        )
        obs_count = int(
            session.exec(
                select(func.count())
                .select_from(ShadowTrade)
                .where(
                    ShadowTrade.validation_run_id == run_id,
                    ShadowTrade.promotion_level == LEVEL_OBSERVED,
                )
            ).one()
            or 0
        )

    scheduler_enabled = bool((cfg.get("autonomous_paper_learning") or {}).get("scheduler_enabled"))
    last_tick_at = sched.get("last_tick_at")
    interval = max(60, int((cfg.get("autonomous_paper_learning") or {}).get("scheduler_interval_seconds", 600)))
    scheduler_seen = bool(scheduler_enabled and _recent_tick(last_tick_at, max_age_seconds=interval * 3))

    diag = sched.get("last_shadow_diagnostics") or {}
    reason_zero = None
    if count == 0 and obs_count == 0:
        reason_zero = diag.get("last_tick_zero_shadow_reason")
        if not reason_zero:
            if not scheduler_enabled:
                reason_zero = "scheduler_off"
            elif not scheduler_seen:
                reason_zero = "scheduler_not_seen"
            else:
                reason_zero = "quality_below_observation_floor"

    ui_state = "enabled_waiting_for_setups"
    if count > 0:
        ui_state = "enabled_tracking_shadow_trades"
    elif obs_count > 0:
        ui_state = "enabled_collecting_observations"

    return {
        "enabled": True,
        "shadow_league_count": count,
        "total_shadow_observations": obs_count,
        "ui_state": ui_state,
        "reason_shadow_count_zero": reason_zero,
        "scheduler_seen": scheduler_seen,
    }


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
    shadow = _shadow_runtime(session, cfg, sched)
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
    alpha_st = _safe(
        lambda: __import__(
            "app.services.autonomous_alpha_factory_service", fromlist=["AutonomousAlphaFactoryService"]
        ).AutonomousAlphaFactoryService(session, cfg).get_status(),
        {},
    )

    live = live_lock_status(cfg)
    paper_broker = bool(pe.get("paper_broker") or is_paper_broker_url())
    paper_orders_enabled = bool(pe.get("paper_orders_enabled") or paper_status.get("paper_orders_enabled"))
    paper_entry_ready = bool(paper_status.get("paper_entry_ready"))
    scheduler_enabled = bool(pe.get("scheduler_enabled") or sched.get("scheduler_enabled"))
    last_tick_at = sched.get("last_tick_at")
    account_synced = bool(
        acct.get("alpaca_connected")
        or acct.get("connected")
        or acct.get("equity") is not None
        or acct.get("last_sync_at")
    )
    # Paper validation: never mark broker offline when paper URL + orders are enabled.
    if paper_broker and paper_orders_enabled:
        broker_connected = True
    elif paper_broker and scheduler_enabled and _recent_tick(last_tick_at):
        broker_connected = True
    else:
        broker_connected = bool(paper_broker and account_synced)

    blockers = uni.get("blocker_summary") or []
    top_blocker = blockers[0] if blockers else None
    paper_candidates = int(alpha_st.get("paper_candidate_count") or 0)

    why_no_trade = None
    if top_blocker:
        why_no_trade = str(top_blocker.get("label") or top_blocker.get("code") or "alpha_not_ready")
    elif paper_candidates == 0:
        why_no_trade = "No approved paper candidate yet"

    tick_in_progress = bool(sched.get("tick_in_progress"))
    tick_lease_held = bool(sched.get("tick_lease_held"))

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
        "last_tick_at": last_tick_at,
        "next_tick_at": sched.get("next_planned_at_utc"),
        "tick_in_progress": tick_in_progress,
        "tick_lease_held": tick_lease_held,
        "tick_lease_stale_recovered": sched.get("tick_lease_stale_recovered"),
        "shadow_league_enabled": bool(shadow.get("enabled", True)),
        "shadow_count": int(shadow.get("shadow_league_count") or 0),
        "reason_shadow_count_zero": shadow.get("reason_shadow_count_zero"),
        "shadow_ui_state": shadow.get("ui_state") or (
            "enabled_waiting_for_setups" if shadow.get("enabled") else "disabled_by_config"
        ),
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
        "data_degraded": False,
        "degraded_reason": None,
        "account_equity": acct.get("equity"),
        "account_last_sync_at": acct.get("last_sync_at") or last_tick_at,
        "note": "Fast runtime truth for global UI — prefer over slow /api/mission-control/status for header chips.",
    }
