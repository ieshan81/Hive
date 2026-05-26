"""Env-var-only global pause — never set by ticks, exports, or broker errors."""

from __future__ import annotations

import os
from typing import Any


def _env_bool(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in ("1", "true", "yes", "on")


def env_pause_status() -> dict[str, Any]:
    paper = _env_bool("PAPER_TRADING_PAUSED_BY_ENV")
    learning = _env_bool("AUTONOMOUS_LEARNING_PAUSED_BY_ENV")
    scheduler = _env_bool("SCHEDULER_PAUSED_BY_ENV")
    return {
        "paper_trading_paused_by_env": paper,
        "autonomous_learning_paused_by_env": learning,
        "scheduler_paused_by_env": scheduler,
        "any_env_pause": paper or learning or scheduler,
        "source": "environment_variables_only",
        "note": "Broker 429, stale quotes, and export failures do not change these flags.",
    }
