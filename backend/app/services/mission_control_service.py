"""Mission Control — single-page operator truth for paper push-pull bot."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.paper_learning_truth import paper_learning_display_status


def mission_control_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    env = env_pause_status()
    lock = live_lock_tripwire_status(cfg)
    paper = paper_learning_display_status(session, cfg)

    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
    from app.services.capital_allocator import CapitalAllocatorService
    from app.services.execution_logs_query_service import list_execution_logs
    from app.services.nuke_epoch_service import nuke_status_export
    from app.services.push_pull_engine_service import PushPullEngineService

    from app.database import LessonNode
    from sqlmodel import select

    nuke_st = nuke_status_export(session)
    lesson_count = len(list(session.exec(select(LessonNode)).all()))
    fresh_brain = lesson_count == 0

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
    blockers = list(paper.get("blockers") or [])
    if env["paper_trading_paused_by_env"]:
        blockers = list(dict.fromkeys(blockers + ["env_pause_paper_trading"]))
    if env["autonomous_learning_paused_by_env"]:
        blockers = list(dict.fromkeys(blockers + ["env_pause_learning"]))

    plain_next = "Next scan running on schedule." if effective_scheduler else "Enable scheduler for automatic scans."
    if not effective_learning:
        plain_next = "Paper learning is off — turn on AI Learning to scan."
    if env["any_env_pause"]:
        plain_next = "Env pause active — remove Railway env pause vars to resume."

    return {
        "status": "ok",
        "fresh_brain": fresh_brain,
        "nuke_status": nuke_st,
        "system_state_banner": {
            "headline": _headline(effective_learning, effective_scheduler, env, lock),
            "subline": plain_next,
            "live_locked": lock.get("live_lock_status") == "locked",
            "paper_broker": bool(lock.get("paper_broker")),
            "degraded": allocator.get("status") == "degraded",
        },
        "push_pull_engine": push_pull,
        "paper_learning": {
            "desired_enabled": desired_learning,
            "effective_enabled": effective_learning,
            "can_place_paper_orders": bool(paper.get("can_place_paper_orders")) and not env["paper_trading_paused_by_env"],
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
        "operator_messages": push_pull.get("operator_messages", []),
    }


def _headline(learning: bool, scheduler: bool, env: dict, lock: dict) -> str:
    if env.get("any_env_pause"):
        return "Env pause active — scans blocked until Railway env vars cleared"
    if not learning:
        return "Paper learning off — push-pull engine idle"
    if scheduler and learning:
        return "Learning active — push-pull scans on schedule"
    return "Learning on — manual or scheduled scans available"
