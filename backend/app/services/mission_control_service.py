"""Mission Control — single-page operator truth for paper push-pull bot."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.paper_learning_blockers import compute_push_pull_blockers, resolve_primary_blocker
from app.services.paper_learning_truth import paper_learning_display_status


def mission_control_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    env = env_pause_status()
    lock = live_lock_tripwire_status(cfg)
    paper = paper_learning_display_status(session, cfg)
    block = compute_push_pull_blockers(session, cfg)

    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
    from app.services.capital_allocator import CapitalAllocatorService
    from app.services.execution_logs_query_service import list_execution_logs
    from app.services.nuke_epoch_service import nuke_status_export
    from app.services.push_pull_engine_service import PushPullEngineService

    nuke_st = nuke_status_export(session)
    lesson_count = len(list(session.exec(select(LessonNode)).all()))
    fresh_brain = lesson_count == 0 or bool(nuke_st.get("post_nuke_lesson_count", 0) == 0)

    sched = AutonomousPaperScheduler(session, cfg).status()
    allocator = CapitalAllocatorService(session, cfg).status_summary()
    push_pull = PushPullEngineService(session, cfg).status()
    latest_logs = list_execution_logs(session, scope="latest_tick", limit=5)

    apl = dict(cfg.get("autonomous_paper_learning") or {})
    desired_learning = bool(apl.get("mode_enabled"))
    desired_scheduler = bool(apl.get("scheduler_enabled"))

    effective_learning = desired_learning and not env["autonomous_learning_paused_by_env"]
    effective_scheduler = (
        desired_scheduler
        and not env["scheduler_paused_by_env"]
        and not sched.get("paused")
    )

    last_tick = push_pull.get("last_tick") or {}
    blockers = list(block.get("blockers_plain") or paper.get("blockers") or [])
    primary = resolve_primary_blocker(block.get("blockers") or [], env)

    can_place = bool(block.get("can_place_paper_orders")) and not env["paper_trading_paused_by_env"]

    plain_next = primary.get("operator_action_required") or "Push-pull paper learning active."
    if effective_scheduler and can_place:
        plain_next = "Scheduler ON — waiting for next push-pull tick or approved candidate."
    elif effective_learning and not can_place:
        plain_next = primary.get("primary_blocker_plain") or plain_next

    show_start_fresh = (
        not env.get("any_env_pause")
        and (not desired_learning or not block.get("paper_orders_enabled") or not desired_scheduler)
    )

    return {
        "status": "ok",
        "fresh_brain": fresh_brain,
        "nuke_status": nuke_st,
        "system_state_banner": {
            "headline": _headline(effective_learning, effective_scheduler, env, lock, can_place),
            "subline": plain_next,
            "live_locked": lock.get("live_lock_status") == "locked",
            "paper_broker": bool(lock.get("paper_broker")),
            "degraded": allocator.get("status") == "degraded",
        },
        "push_pull_engine": push_pull,
        "paper_learning": {
            "desired_enabled": desired_learning,
            "effective_enabled": effective_learning,
            "can_place_paper_orders": can_place,
            "paper_learning_on": "ON" if desired_learning else "OFF",
            "paper_execution_on": "ON" if block.get("paper_orders_enabled") else "OFF",
        },
        "scheduler": {
            "desired_enabled": desired_scheduler,
            "effective_enabled": effective_scheduler,
            **sched,
        },
        "env_pause": env,
        "live_lock": lock,
        "last_tick_summary": last_tick,
        "last_execution_logs": latest_logs.get("execution_logs", []),
        "capital_allocator": allocator,
        "blockers": blockers,
        "blocker_codes": block.get("blockers", []),
        "can_place_paper_orders": can_place,
        "primary_blocker": primary.get("primary_blocker"),
        "primary_blocker_plain": primary.get("primary_blocker_plain"),
        "blocker_category": primary.get("blocker_category"),
        "operator_action_required": primary.get("operator_action_required"),
        "next_action_label": primary.get("next_action_label"),
        "next_action_endpoint": primary.get("next_action_endpoint"),
        "show_start_fresh_button": show_start_fresh,
        "next_action_plain": plain_next,
        "operator_messages": push_pull.get("operator_messages", []),
    }


def _headline(learning: bool, scheduler: bool, env: dict, lock: dict, can_place: bool) -> str:
    if env.get("any_env_pause"):
        return "Env pause active — scans blocked until Railway env vars cleared"
    if not learning:
        return "Paper learning OFF — use Start Fresh Paper Learning"
    if can_place and scheduler:
        return "Paper learning ON — push-pull scans on schedule"
    if learning and not can_place:
        return "Paper learning ON — execution blocked (see reason below)"
    return "Paper learning ON — enable scheduler for automatic ticks"
