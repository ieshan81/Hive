"""Mission Control — single-page operator truth for paper push-pull bot."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.capital_allocator import CapitalAllocatorService
from app.services.config_manager import ConfigManager
from app.services.execution_logs_query_service import list_execution_logs
from app.services.product_truth_service import product_truth
from app.services.push_pull_engine_service import PushPullEngineService


def mission_control_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    truth = product_truth(session, cfg)
    push_pull = PushPullEngineService(session, cfg).status()
    allocator = CapitalAllocatorService(session, cfg).status_summary()
    latest_logs = list_execution_logs(session, scope="latest_tick", limit=5)
    last_tick = push_pull.get("last_tick") or {}

    env = truth.get("env_pause_status") or {}
    headline = _headline(truth, env)

    return {
        "status": "ok",
        **truth,
        "fresh_brain": truth.get("fresh_brain"),
        "nuke_status": truth.get("nuke_status"),
        "system_state_banner": {
            "headline": headline,
            "subline": truth.get("operator_next_action") or last_tick.get("plain"),
            "live_locked": truth.get("live_lock_status") == "locked",
            "paper_broker": truth.get("paper_broker_status") == "paper",
            "degraded": allocator.get("status") == "degraded",
        },
        "push_pull_engine": push_pull,
        "paper_learning": {
            "desired_enabled": truth.get("operator_desired_paper_learning"),
            "effective_enabled": truth.get("effective_can_scan"),
            "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
            "paper_learning_on": "ON" if truth.get("operator_desired_paper_learning") else "OFF",
            "paper_execution_on": "ON" if truth.get("operator_desired_paper_execution") else "OFF",
        },
        "scheduler": truth.get("scheduler") or {},
        "env_pause": env,
        "live_lock": {"live_lock_status": truth.get("live_lock_status")},
        "last_tick_summary": last_tick,
        "last_execution_logs": latest_logs.get("execution_logs", []),
        "capital_allocator": allocator,
        "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
        "next_action_plain": truth.get("operator_next_action"),
    }


def _headline(truth: dict, env: dict) -> str:
    if env.get("any_env_pause"):
        return "Env pause active — execution blocked until Railway env vars cleared"
    mode = truth.get("current_mode")
    if mode == "paper_learning_off":
        return "Paper learning OFF — use Start Fresh Paper Learning"
    if mode == "push_pull_paper_learning":
        return "Push-Pull Paper Learning active — scans on schedule"
    if mode == "push_pull_scanning":
        return "Push-Pull scanning — waiting for entry or fixing blocker"
    return truth.get("current_mode_label") or "System status"
