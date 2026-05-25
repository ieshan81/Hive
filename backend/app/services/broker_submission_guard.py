"""Central guard — no broker order submission unless paper URL confirmed."""

from __future__ import annotations

from typing import Any

from app.services.broker_safety import is_paper_broker_url
from app.services.live_lock_tripwire import assert_live_blocked


def blocked_submission_result(reason: str, *, detail: str | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "error": reason,
        "blocked": True,
        "detail": detail or reason,
        "paper_only": True,
    }


def assert_paper_submission_allowed(config: dict | None = None) -> tuple[bool, str]:
    """Returns (allowed, reason_code)."""
    if not is_paper_broker_url():
        return False, "BROKER_NOT_PAPER"
    if config is not None:
        ok, code = assert_live_blocked(config)
        if not ok:
            return False, code
    import os

    if int(os.environ.get("LIVE_TRADING_ARMED", "0") or 0) == 1:
        return False, "LIVE_TRADING_ARMED_ENV"
    if int(os.environ.get("PROMOTION_GATES_PASSED", "0") or 0) == 1 and not is_paper_broker_url():
        return False, "PROMOTION_GATES_LIVE"
    return True, "ok"


def guard_before_submit(config: dict | None = None) -> dict[str, Any] | None:
    """Return blocked result dict if submission must not proceed, else None."""
    allowed, code = assert_paper_submission_allowed(config)
    if allowed:
        return None
    return blocked_submission_result(code)
