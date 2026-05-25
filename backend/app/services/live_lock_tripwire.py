"""Live lock tripwire — API key / env changes cannot arm live trading."""

from __future__ import annotations

import os
from typing import Any

from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status
from app.services.engine_config import cfg_get


def live_lock_tripwire_status(config: dict) -> dict[str, Any]:
    """Audit-visible status: env + config must agree on paper-only."""
    base = broker_base_url()
    paper_url = is_paper_broker_url()
    live_enabled = bool(cfg_get(config, "execution.live_orders_enabled", False))
    live_flag = bool(config.get("live_trading_enabled", False))
    armed = int(os.environ.get("LIVE_TRADING_ARMED", "0") or 0)
    gates = int(os.environ.get("PROMOTION_GATES_PASSED", "0") or 0)
    tripwire_ok = paper_url and not live_enabled and not live_flag
    return {
        "status": "ok",
        "tripwire_ok": tripwire_ok,
        "broker_base_url": base,
        "paper_broker": paper_url,
        "live_orders_enabled": live_enabled,
        "live_trading_enabled": live_flag,
        "LIVE_TRADING_ARMED": armed,
        "PROMOTION_GATES_PASSED": gates,
        "broker_mode_confirmed_live": False,
        "api_key_swap_unlocks_live": False,
        "message": "Simple API key swap cannot enable live — all gates required",
        **live_lock_status(config),
    }


def assert_live_blocked(config: dict) -> tuple[bool, str]:
    st = live_lock_tripwire_status(config)
    if st.get("live_orders_enabled") or st.get("live_trading_enabled"):
        return False, "live_flags_set"
    if not st.get("paper_broker"):
        return False, "broker_not_paper"
    return True, "ok"
