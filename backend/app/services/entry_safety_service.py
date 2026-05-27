"""Temporary entry safety while system degraded — exits still allowed."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.mission_control_snapshot_service import _CACHE, _data_freshness_label, _snapshot_age_seconds
from app.services.radar_resilience import last_successful_scan
from app.services.system_db_pool_service import db_pool_status


def entry_safety_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    lock = live_lock_tripwire_status(cfg)
    env = env_pause_status()
    pool = db_pool_status()
    radar = last_successful_scan()

    blockers: list[str] = []
    warnings: list[str] = []

    if lock.get("live_lock_status") != "locked":
        blockers.append("live_trading_not_locked")
    if env.get("any_env_pause"):
        blockers.append("env_pause_active")

    if pool.get("degraded"):
        blockers.append("db_pool_degraded")
        warnings.append(pool.get("message") or "Database connection pool under stress")

    age = _snapshot_age_seconds()
    freshness = _data_freshness_label(age)
    if freshness in ("stale", "very_stale", "unknown") or not _CACHE.get("cockpit"):
        blockers.append("system_snapshot_degraded")
        warnings.append("Mission Control snapshot stale or not yet built")

    if not radar.get("cached_snapshot_available"):
        blockers.append("universe_snapshot_stale")
        warnings.append("Universe radar cache empty")

    new_entries_allowed = len(blockers) == 0
    return {
        "status": "ok" if new_entries_allowed else "degraded",
        "new_paper_entries_allowed": new_entries_allowed,
        "exit_monitor_active": True,
        "live_trading_locked": lock.get("live_lock_status") == "locked",
        "paper_broker": bool(lock.get("paper_broker")),
        "blockers": blockers,
        "warnings": warnings,
        "snapshot_age_seconds": round(age, 1) if age is not None else None,
        "data_freshness": freshness,
        "operator_message": (
            "Push-pull paper learning active; new entries allowed when data is fresh."
            if new_entries_allowed
            else "New paper entries paused because system state is degraded. Exit monitoring remains active."
        ),
    }
