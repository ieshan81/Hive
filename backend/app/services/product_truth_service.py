"""Single product truth model — Mission Control, Paper Learning, Push-Pull, banner."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select, func

from app.database import LessonNode
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.nuke_epoch_service import get_latest_reset_epoch, nuke_status_export
from app.services.paper_learning_blockers import compute_push_pull_blockers, resolve_primary_blocker
from app.services.session_engine import SessionEngine


def product_truth(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    env = env_pause_status()
    lock = live_lock_tripwire_status(cfg)
    block = compute_push_pull_blockers(session, cfg)
    epoch = get_latest_reset_epoch(session)
    nuke_st = nuke_status_export(session)

    apl = dict(cfg.get("autonomous_paper_learning") or {})
    desired_learning = bool(apl.get("mode_enabled"))
    desired_scheduler = bool(apl.get("scheduler_enabled"))
    desired_execution = bool((cfg.get("execution") or {}).get("paper_orders_enabled"))

    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    sched = AutonomousPaperScheduler(session, cfg).status()

    effective_learning = desired_learning and not env["autonomous_learning_paused_by_env"]
    effective_scheduler = (
        desired_scheduler and not env["scheduler_paused_by_env"] and not sched.get("paused")
    )
    effective_execution = desired_execution and not env["paper_trading_paused_by_env"]

    can_scan = effective_learning and not env["any_env_pause"]
    can_tick = can_scan and effective_scheduler
    can_place = bool(block.get("can_place_paper_orders")) and effective_execution

    if env["any_env_pause"]:
        current_mode = "env_paused"
    elif not desired_learning:
        current_mode = "paper_learning_off"
    elif can_place:
        current_mode = "push_pull_paper_learning"
    elif effective_learning:
        current_mode = "push_pull_scanning"
    else:
        current_mode = "off"

    primary = resolve_primary_blocker(block.get("blockers") or [], env)
    lesson_count = session.exec(select(func.count()).select_from(LessonNode)).one()
    fresh_brain = lesson_count == 0 or nuke_st.get("post_nuke_lesson_count", 0) == 0

    sess = SessionEngine().detect()
    market_label = sess.to_dict().get("crypto_display") or sess.mode

    return {
        "status": "ok",
        "live_lock_status": lock.get("live_lock_status"),
        "paper_broker_status": "paper" if lock.get("paper_broker") else "unknown",
        "env_pause_status": env,
        "operator_desired_paper_learning": desired_learning,
        "operator_desired_scheduler": desired_scheduler,
        "operator_desired_paper_execution": desired_execution,
        "effective_can_scan": can_scan,
        "effective_can_tick": can_tick,
        "effective_can_place_paper_orders": can_place,
        "current_mode": current_mode,
        "current_mode_label": _mode_label(current_mode),
        "primary_blocker": primary.get("primary_blocker"),
        "primary_blocker_plain": primary.get("primary_blocker_plain"),
        "blocker_category": primary.get("blocker_category"),
        "operator_next_action": primary.get("operator_action_required"),
        "next_action_label": primary.get("next_action_label"),
        "next_action_endpoint": primary.get("next_action_endpoint"),
        "reset_epoch_id": (epoch or {}).get("reset_epoch_id"),
        "fresh_brain": fresh_brain,
        "nuke_status": nuke_st,
        "blockers": block.get("blockers_plain", []),
        "blocker_codes": block.get("blockers", []),
        "scheduler": sched,
        "market_mode": market_label,
        "show_start_fresh_button": not env.get("any_env_pause")
        and (not desired_learning or not desired_execution or not desired_scheduler),
    }


def _mode_label(mode: str) -> str:
    return {
        "push_pull_paper_learning": "Push-Pull Paper Learning",
        "push_pull_scanning": "Push-Pull Scanning",
        "paper_learning_off": "Paper Learning OFF",
        "env_paused": "Env Pause Active",
        "off": "Off",
    }.get(mode, mode.replace("_", " ").title())
