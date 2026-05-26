"""Hard paper-only assertion — no order path without passing this gate."""

from __future__ import annotations

import os
from typing import Any

from app.config import settings
from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status, paper_execution_blockers
from app.services.engine_config import cfg_get, current_promotion_stage


class PaperGuardViolation(Exception):
    """Raised when any live or unsafe broker path is attempted."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def assert_paper_only(config: dict, *, alpaca_configured: bool = True, context: str = "order_submit") -> None:
    """
    Non-negotiable assertion before any Alpaca trading API call.
    Raises PaperGuardViolation on failure.
    """
    if bool(cfg_get(config, "execution.live_orders_enabled", False)):
        raise PaperGuardViolation("LIVE_ORDERS_ENABLED", f"{context}: live orders flag is set")
    if bool(config.get("live_trading_enabled", False)):
        raise PaperGuardViolation("LIVE_TRADING_ENABLED", f"{context}: live_trading_enabled in config")
    if int(os.environ.get("LIVE_TRADING_ARMED", "0") or 0) == 1:
        raise PaperGuardViolation("LIVE_TRADING_ARMED", f"{context}: LIVE_TRADING_ARMED env set")
    if current_promotion_stage(config) != "PAPER":
        raise PaperGuardViolation("PROMOTION_NOT_PAPER", f"{context}: promotion stage is not PAPER")
    if not is_paper_broker_url():
        raise PaperGuardViolation(
            "BROKER_NOT_PAPER",
            f"{context}: Alpaca base URL must be paper-api.alpaca.markets (got {broker_base_url()})",
        )
    if not alpaca_configured and settings.alpaca_configured is False:
        raise PaperGuardViolation("ALPACA_NOT_CONFIGURED", f"{context}: Alpaca credentials missing")
    blockers = paper_execution_blockers(config, alpaca_configured=alpaca_configured)
    if blockers:
        raise PaperGuardViolation(blockers[0], f"{context}: {', '.join(blockers)}")


def paper_guard_status(config: dict, *, alpaca_configured: bool = True) -> dict[str, Any]:
    """Operator-visible paper cage status."""
    blockers = paper_execution_blockers(config, alpaca_configured=alpaca_configured)
    return {
        "paper_only_enforced": True,
        "broker_base_url": broker_base_url(),
        "is_paper_broker_url": is_paper_broker_url(),
        "blockers": blockers,
        "ready": len(blockers) == 0,
        **live_lock_status(config),
    }
