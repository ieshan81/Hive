"""Read-only Shadow League status for minimal UI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ShadowTrade
from app.services.shadow_league_bundle_service import (
    shadow_trades_summary,
    strategy_promotion_ladder,
    why_no_trade,
)
from app.services.shadow_league_constants import LEVEL_OBSERVED, LEVEL_SHADOW_TRADE
from app.services.shadow_trade_service import shadow_league_enabled


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except ValueError:
        return None


def _scheduler_state(session: Session, config: dict) -> dict[str, Any]:
    try:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        return AutonomousPaperScheduler(session, config).status()
    except Exception:
        return {}


def _reason_shadow_count_zero(
    *,
    enabled: bool,
    scheduler_enabled: bool,
    scheduler_seen: bool,
    total_count: int,
    scheduler_state: dict[str, Any],
) -> Optional[str]:
    if not enabled:
        return "shadow_league_disabled"
    if not scheduler_enabled:
        return "scheduler_off"
    if not scheduler_seen:
        return "scheduler_not_seen"
    if total_count > 0:
        return None
    diag = scheduler_state.get("last_shadow_diagnostics") or scheduler_state
    measurable = diag.get("last_tick_zero_shadow_reason")
    if measurable:
        return str(measurable)
    last_obs = int(
        scheduler_state.get("last_tick_shadow_observations_created")
        or scheduler_state.get("last_shadow_setups_observed")
        or 0
    )
    last_trade = int(scheduler_state.get("last_tick_shadow_trades_created") or 0)
    if last_obs == 0 and last_trade == 0 and scheduler_state.get("last_tick_at"):
        return "quality_below_observation_floor"
    if scheduler_state.get("last_shadow_error"):
        return "exception"
    return "no_rows_scored"


def _ui_state(
    *,
    enabled: bool,
    scheduler_enabled: bool,
    total_count: int,
    trade_count: int,
    obs_count: int,
    reason_zero: Optional[str],
) -> str:
    if not enabled:
        return "disabled_by_config"
    if not scheduler_enabled:
        return "enabled_waiting_for_setups"
    if total_count == 0:
        if reason_zero in ("no_eligible_setups_met_observation_floor", "no_observations_yet_after_tick"):
            return "enabled_waiting_for_setups"
        return "enabled_waiting_for_setups"
    if trade_count > 0:
        return "enabled_tracking_shadow_trades"
    if obs_count > 0:
        return "enabled_collecting_observations"
    return "enabled_waiting_for_setups"


def build_shadow_league_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.config_manager import ConfigManager

    cfg = config or ConfigManager(session).get_current_readonly()
    if not shadow_league_enabled(cfg):
        return {"status": "disabled", "enabled": False, "ui_state": "disabled_by_config"}

    summary = shadow_trades_summary(session, cfg)
    ladder = strategy_promotion_ladder(session, cfg)
    wnt = why_no_trade(session, cfg)
    closest = ladder.get("closest_to_paper_promotion") or {}
    run_id = summary.get("validation_run_id")

    rows = list(
        session.exec(select(ShadowTrade).where(ShadowTrade.validation_run_id == run_id)).all()
    )
    obs_rows = [r for r in rows if r.promotion_level == LEVEL_OBSERVED]
    trade_rows = [r for r in rows if r.promotion_level >= LEVEL_SHADOW_TRADE]
    crypto_n = sum(1 for r in rows if str(r.asset_class or "").lower() == "crypto")
    stock_n = sum(1 for r in rows if str(r.asset_class or "").lower() == "stock")

    last_obs_at = None
    if obs_rows:
        last_obs_at = max((r.created_at for r in obs_rows if r.created_at), default=None)
    last_trade_at = None
    if trade_rows:
        last_trade_at = max((r.created_at for r in trade_rows if r.created_at), default=None)

    sched = _scheduler_state(session, cfg)
    tick_diag = dict(sched.get("last_shadow_diagnostics") or {})
    if not tick_diag.get("observation_floor"):
        from app.services.shadow_tick_diagnostics import build_shadow_tick_diagnostics

        tick_diag = build_shadow_tick_diagnostics(
            cfg,
            rows_scored=0,
            rows_above_observation_floor=0,
            rows_above_shadow_floor=0,
            max_setup_quality=0.0,
            quality_scale="0_100",
            shadow_attempts=0,
            shadow_observations_created=0,
            shadow_trades_created=0,
            shadow_errors=0,
            near_misses=[],
            skip_reason_counts={},
        )
    scheduler_enabled = bool(cfg.get("autonomous_paper_learning", {}).get("scheduler_enabled"))
    last_tick = _parse_ts(sched.get("last_tick_at"))
    interval = max(60, int((cfg.get("autonomous_paper_learning") or {}).get("scheduler_interval_seconds", 600)))
    scheduler_seen = bool(
        scheduler_enabled
        and last_tick
        and (datetime.utcnow() - last_tick).total_seconds() <= interval * 2.5
    )

    total_count = int(summary.get("shadow_league_count") or 0)
    reason_zero = _reason_shadow_count_zero(
        enabled=True,
        scheduler_enabled=scheduler_enabled,
        scheduler_seen=scheduler_seen,
        total_count=total_count,
        scheduler_state=sched,
    )
    ui_state = _ui_state(
        enabled=True,
        scheduler_enabled=scheduler_enabled,
        total_count=total_count,
        trade_count=len(trade_rows),
        obs_count=len(obs_rows),
        reason_zero=reason_zero,
    )

    return {
        "status": "ok",
        "enabled": True,
        "ui_state": ui_state,
        "shadow_league_count": total_count,
        "open_shadow_trades": summary.get("open_shadow_trades", 0),
        "total_shadow_observations": len(obs_rows),
        "total_shadow_trades": len(trade_rows),
        "crypto_shadow_count": crypto_n,
        "stock_shadow_count": stock_n,
        "last_shadow_observation_at": last_obs_at.isoformat() + "Z" if last_obs_at else None,
        "last_shadow_trade_at": last_trade_at.isoformat() + "Z" if last_trade_at else None,
        "scheduler_seen": scheduler_seen,
        "scheduler_enabled": scheduler_enabled,
        "last_tick_at": sched.get("last_tick_at"),
        "next_tick_at": sched.get("next_planned_at_utc"),
        "last_tick_shadow_observations": sched.get("last_shadow_setups_observed"),
        "last_tick_shadow_trades_created": sched.get("last_shadow_trades_created"),
        "closest_to_paper_promotion": closest,
        "closest_setup": closest,
        "missing_evidence": closest.get("missing_evidence") or [],
        "reason_shadow_count_zero": reason_zero,
        "last_tick_zero_shadow_reason": tick_diag.get("last_tick_zero_shadow_reason"),
        "observation_floor": tick_diag.get("observation_floor"),
        "shadow_floor": tick_diag.get("shadow_floor"),
        "max_setup_quality_last_tick": tick_diag.get("max_setup_quality_last_tick"),
        "rows_scored_last_tick": tick_diag.get("rows_scored_last_tick"),
        "rows_above_observation_floor": tick_diag.get("rows_above_observation_floor"),
        "rows_above_shadow_floor": tick_diag.get("rows_above_shadow_floor"),
        "last_tick_shadow_attempts": tick_diag.get("last_tick_shadow_attempts"),
        "last_tick_shadow_observations_created": tick_diag.get("last_tick_shadow_observations_created"),
        "last_tick_shadow_trades_created": tick_diag.get("last_tick_shadow_trades_created"),
        "near_misses_top_10": tick_diag.get("near_misses_top_10") or [],
        "skip_reason_counts": tick_diag.get("skip_reason_counts") or {},
        "push_pull_shadow_observer_ran": tick_diag.get("push_pull_shadow_observer_ran"),
        "by_level": ladder.get("by_level"),
        "why_no_trade_plain": wnt.get("plain"),
        "counts_as_broker_evidence": False,
        "broker_evidence_count": 0,
        "live_trading_locked": True,
        "note": "Shadow league is learning-only; no broker orders.",
    }
