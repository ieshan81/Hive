"""Push-pull paper learning blockers — no legacy fast-training codes in operator UI."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.env_pause_service import env_pause_status


# Internal codes → plain operator language (Mission Control / dashboard).
BLOCKER_LABELS: dict[str, str] = {
    "env_pause_paper_trading": "Paper execution blocked by Railway env pause (PAPER_TRADING_PAUSED_BY_ENV).",
    "env_pause_learning": "Paper learning blocked by Railway env pause (AUTONOMOUS_LEARNING_PAUSED_BY_ENV).",
    "env_pause_scheduler": "Scheduler blocked by Railway env pause (SCHEDULER_PAUSED_BY_ENV).",
    "paper_learning_off": "Paper learning is OFF. Use Start Fresh Paper Learning on Mission Control.",
    "paper_execution_off": "Paper execution is OFF. Enable paper orders to place trades.",
    "scheduler_off": "Scheduler is OFF. Enable scheduler for automatic push-pull ticks.",
    "scheduler_paused": "Scheduler is paused.",
    "broker_not_paper": "Broker is not paper — live safety blocked.",
    "live_lock_not_locked": "Live lock tripwire failed — trading blocked.",
    "ghost_positions": "Ghost position candidates need review before new entries.",
    "broker_sync_rate_limited": "Broker sync is rate-limited — wait and retry.",
    "allocator_degraded": "Capital allocator degraded — broker data stale or buying power unknown.",
    "live_trading_flag_set": "Live trading flag must stay false.",
    "kill_switch_active": "Paper entries are blocked by the kill switch.",
}


def friendly_blocker(code: str) -> str:
    if code.startswith("scheduler_paused:"):
        reason = code.split(":", 1)[-1]
        return f"Scheduler paused ({reason.replace('_', ' ')})."
    return BLOCKER_LABELS.get(code, code.replace("_", " "))


def compute_push_pull_blockers(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Single blocker model for push-pull paper learning (not fast-training legacy)."""
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
    from app.services.broker_reconciliation_service import BrokerReconciliationService
    from app.services.capital_allocator import CapitalAllocatorService
    from app.services.kill_switch_service import KillSwitchService
    from app.services.live_lock_tripwire import live_lock_tripwire_status

    cfg = config or ConfigManager(session).get_current()
    env = env_pause_status()
    apl = dict(cfg.get("autonomous_paper_learning") or {})
    sched = AutonomousPaperScheduler(session, cfg).status()
    mode_on = bool(apl.get("mode_enabled"))
    paper_orders = bool(cfg_get(cfg, "execution.paper_orders_enabled", False))
    scheduler_on = bool(apl.get("scheduler_enabled"))
    scheduler_running = scheduler_on and not sched.get("paused")

    blockers: list[str] = []
    if env["paper_trading_paused_by_env"]:
        blockers.append("env_pause_paper_trading")
    if env["autonomous_learning_paused_by_env"]:
        blockers.append("env_pause_learning")
    if env["scheduler_paused_by_env"]:
        blockers.append("env_pause_scheduler")
    if not paper_orders:
        blockers.append("paper_execution_off")
    if not mode_on:
        blockers.append("paper_learning_off")
    if not scheduler_on:
        blockers.append("scheduler_off")
    elif sched.get("paused"):
        blockers.append(f"scheduler_paused:{sched.get('paused_reason') or 'unknown'}")

    trip = live_lock_tripwire_status(cfg)
    if trip.get("live_lock_status") != "locked":
        blockers.append("live_lock_not_locked")
    if bool(cfg.get("live_trading_enabled", False)):
        blockers.append("live_trading_flag_set")

    kill = KillSwitchService(session, cfg).status()
    if not bool(kill.get("entries_allowed")):
        blockers.append("kill_switch_active")

    ghosts = BrokerReconciliationService(session, cfg).ghost_position_candidates()
    if ghosts:
        blockers.append("ghost_positions")

    if AlpacaAdapter(session).broker_sync_rate_limited:
        blockers.append("broker_sync_rate_limited")

    alloc: dict[str, Any] = {}
    try:
        alloc = CapitalAllocatorService(session, cfg).status_summary()
        if alloc.get("status") == "degraded":
            blockers.append("allocator_degraded")
    except Exception:
        blockers.append("allocator_degraded")

    can_place = (
        mode_on
        and paper_orders
        and not env["any_env_pause"]
        and trip.get("live_lock_status") == "locked"
        and bool(kill.get("entries_allowed"))
        and not ghosts
        and "broker_sync_rate_limited" not in blockers
        and "allocator_degraded" not in blockers
    )

    return {
        "blockers": blockers,
        "blockers_plain": [friendly_blocker(b) for b in blockers],
        "can_place_paper_orders": can_place,
        "kill_switch": kill,
        "mode_enabled": mode_on,
        "paper_orders_enabled": paper_orders,
        "scheduler_enabled": scheduler_on,
        "scheduler_running": scheduler_running,
        "allocator": alloc,
    }


def resolve_primary_blocker(blockers: list[str], env: dict[str, Any]) -> dict[str, Any]:
    """One clear reason for Mission Control."""
    if env.get("any_env_pause"):
        if env.get("paper_trading_paused_by_env"):
            return _primary(
                "env_pause_paper_trading",
                "env_pause",
                "Remove Railway env pause vars to resume paper trading.",
                None,
            )
        return _primary(
            "env_pause_learning",
            "env_pause",
            "Remove Railway env pause vars to resume learning.",
            None,
        )
    priority = [
        "paper_execution_off",
        "paper_learning_off",
        "scheduler_off",
        "scheduler_paused",
        "ghost_positions",
        "kill_switch_active",
        "broker_sync_rate_limited",
        "allocator_degraded",
        "live_lock_not_locked",
    ]
    for code in priority:
        for b in blockers:
            if b == code or b.startswith(f"{code}:"):
                return _primary(
                    b,
                    _category(b),
                    _action_for(b),
                    _endpoint_for(b),
                )
    return _primary(
        "ready",
        "ready",
        "Push-pull paper learning is active. Waiting for next tick or approved candidate.",
        "/api/autonomous-paper-learning/tick",
    )


def _primary(code: str, category: str, action: str, endpoint: Optional[str]) -> dict[str, Any]:
    return {
        "primary_blocker": code,
        "blocker_category": category,
        "operator_action_required": action,
        "next_action_label": action.split(".")[0] if action else "Continue",
        "next_action_endpoint": endpoint,
        "primary_blocker_plain": friendly_blocker(code) if code != "ready" else action,
    }


def _category(code: str) -> str:
    if code.startswith("env_pause"):
        return "env_pause"
    if "paper_execution" in code or code == "paper_execution_off":
        return "paper_execution"
    if "paper_learning" in code or code == "paper_learning_off":
        return "paper_learning"
    if "scheduler" in code:
        return "scheduler"
    if "ghost" in code:
        return "reconciliation"
    if "allocator" in code:
        return "allocator"
    if "broker" in code:
        return "broker"
    return "safety"


def _action_for(code: str) -> str:
    actions = {
        "paper_execution_off": "Turn on paper execution with Start Fresh Paper Learning.",
        "paper_learning_off": "Turn on paper learning with Start Fresh Paper Learning.",
        "scheduler_off": "Enable the push-pull scheduler with Start Fresh Paper Learning.",
    }
    if code.startswith("scheduler_paused"):
        return "Clear scheduler pause or run Start Fresh Paper Learning."
    return actions.get(code, friendly_blocker(code))


def _endpoint_for(code: str) -> Optional[str]:
    endpoints = {
        "paper_execution_off": "/api/autonomous-paper-learning/start-fresh",
        "paper_learning_off": "/api/autonomous-paper-learning/start-fresh",
        "scheduler_off": "/api/autonomous-paper-learning/start-fresh",
    }
    if code.startswith("scheduler_paused"):
        return "/api/autonomous-paper-learning/start-fresh"
    return endpoints.get(code)
