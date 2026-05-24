"""Broker mode detection — paper-only execution guard."""

from __future__ import annotations

from app.config import settings
from app.services.engine_config import cfg_get, current_promotion_stage


PAPER_HOST = "paper-api.alpaca.markets"


def broker_base_url() -> str:
    return (settings.alpaca_base_url or "").strip().rstrip("/")


def is_paper_broker_url(url: str | None = None) -> bool:
    u = (url or broker_base_url()).lower()
    return PAPER_HOST in u


def live_lock_status(config: dict) -> dict:
    stage = current_promotion_stage(config)
    live_enabled = bool(cfg_get(config, "execution.live_orders_enabled", False))
    return {
        "promotion_stage": stage,
        "live_orders_enabled": live_enabled,
        "live_trading_enabled": bool(config.get("live_trading_enabled", False)),
        "LIVE_TRADING_ARMED": 0,
        "PROMOTION_GATES_PASSED": 0,
        "live_lock_status": "locked" if not live_enabled and stage == "PAPER" else "restricted",
    }


def paper_execution_blockers(config: dict, *, alpaca_configured: bool) -> list[str]:
    blockers: list[str] = []
    if not alpaca_configured:
        blockers.append("ALPACA_NOT_CONFIGURED")
    if not is_paper_broker_url():
        blockers.append("BROKER_NOT_PAPER")
    if not bool(cfg_get(config, "execution.paper_orders_enabled", False)):
        blockers.append("PAPER_EXECUTION_DISABLED")
    if bool(cfg_get(config, "execution.live_orders_enabled", False)):
        blockers.append("LIVE_TRADING_NOT_ALLOWED_IN_PAPER_MODE")
    if bool(config.get("kill_switch_active")) or bool(cfg_get(config, "kill.manual_master_active", False)):
        blockers.append("KILL_SWITCH_ACTIVE")
    if current_promotion_stage(config) != "PAPER":
        blockers.append("PROMOTION_STAGE_NOT_PAPER")
    return blockers
