"""Absolute hard caps for the paper autopilot — single source of truth.

These caps are ABSOLUTE: they are enforced even when
``autonomous_paper_learning.use_capital_allocator`` is True (the
"opportunity-based" mode), which otherwise zeroes the soft rate caps in
``execution.*`` and the scheduler. An operator may raise or lower them via
operator-gated config, but they can never be disabled to "unlimited" — a
configured value of 0/negative falls back to the protective default.

Nothing here places, cancels, or mutates orders. Read-only counting +
limit resolution only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, PositionSnapshot

# Protective defaults. The autopilot may run for 1–2 weeks unattended, so these
# are intentionally conservative.
ABSOLUTE_CAP_DEFAULTS: dict[str, int] = {
    "absolute_max_scheduler_ticks_per_day": 48,
    "absolute_max_new_entries_per_day": 6,
    "absolute_max_new_entries_per_hour": 2,
    "absolute_max_orders_per_cycle": 1,
    "absolute_max_open_positions": 3,
    "auto_pause_after_consecutive_broker_errors": 3,
    "auto_pause_after_consecutive_rejections": 3,
}

# Order statuses that represent a real, live/working or filled order (i.e. one
# that consumed a "slot"). Rejected/blocked/cancelled are intentionally excluded.
LIVE_OR_FILLED_STATUSES: tuple[str, ...] = (
    "paper_order_submitted",
    "paper_order_filled",
    "paper_order_partially_filled",
)


def resolve_cap(config: dict, key: str) -> int:
    """Resolve an absolute cap. 0/negative/invalid → protective default (never unlimited)."""
    apl = (config or {}).get("autonomous_paper_learning") or {}
    default = ABSOLUTE_CAP_DEFAULTS[key]
    try:
        value = int(apl.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def all_caps(config: dict) -> dict[str, int]:
    return {key: resolve_cap(config, key) for key in ABSOLUTE_CAP_DEFAULTS}


def _count_orders(
    session: Session,
    *,
    side: Optional[str] = None,
    hours: float = 0.0,
    days: float = 0.0,
) -> int:
    query = select(ExecutionLog).where(ExecutionLog.status.in_(LIVE_OR_FILLED_STATUSES))
    if side:
        query = query.where(ExecutionLog.side == side)
    since: Optional[datetime] = None
    if days:
        since = datetime.utcnow() - timedelta(days=days)
    elif hours:
        since = datetime.utcnow() - timedelta(hours=hours)
    if since is not None:
        query = query.where(ExecutionLog.submitted_at >= since)
    # len(.all()) (not func.count) to match the repo's preflight-testing
    # convention so FakeSession stubs in verifiers work; volumes are tiny (capped).
    return len(list(session.exec(query).all()))


def new_entries_today(session: Session) -> int:
    return _count_orders(session, side="buy", days=1)


def new_entries_this_hour(session: Session) -> int:
    return _count_orders(session, side="buy", hours=1)


def open_position_count(session: Session) -> int:
    return len(list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()))


def replaces_fixed_daily_entry_cap(config: dict) -> bool:
    """True when adaptive opportunity budget replaces the fixed daily entry count gate."""
    apl = (config or {}).get("autonomous_paper_learning") or {}
    ob = apl.get("opportunity_budget") or {}
    return bool(ob.get("enabled", True))


def cap_status(session: Session, config: dict) -> dict[str, Any]:
    """Read-only snapshot of every absolute cap, current usage, and which (if any) is hit."""
    caps = all_caps(config)
    entries_day = new_entries_today(session)
    entries_hour = new_entries_this_hour(session)
    open_pos = open_position_count(session)
    retired_daily = replaces_fixed_daily_entry_cap(config)

    hit_reasons: list[str] = []
    if not retired_daily and entries_day >= caps["absolute_max_new_entries_per_day"]:
        hit_reasons.append("absolute_max_new_entries_per_day")
    if entries_hour >= caps["absolute_max_new_entries_per_hour"]:
        hit_reasons.append("absolute_max_new_entries_per_hour")
    if open_pos >= caps["absolute_max_open_positions"]:
        hit_reasons.append("absolute_max_open_positions")

    result: dict[str, Any] = {
        "absolute_caps": caps,
        "new_entries_today": entries_day,
        "new_entries_this_hour": entries_hour,
        "open_positions": open_pos,
        "entries_today_remaining": None
        if retired_daily
        else max(0, caps["absolute_max_new_entries_per_day"] - entries_day),
        "entries_hour_remaining": max(0, caps["absolute_max_new_entries_per_hour"] - entries_hour),
        "open_positions_remaining": max(0, caps["absolute_max_open_positions"] - open_pos),
        "entry_cap_hit": bool(hit_reasons),
        "entry_cap_hit_reasons": hit_reasons,
    }

    if retired_daily:
        result.update(
            {
                "daily_entry_cap_mode": "retired",
                "daily_entry_count_is_blocking": False,
                "active_trade_gate": "adaptive_opportunity_budget",
                "absolute_max_new_entries_per_day_semantics": {
                    "value": caps["absolute_max_new_entries_per_day"],
                    "mode": "legacy_telemetry",
                    "blocking": False,
                },
            }
        )
    else:
        result.update(
            {
                "daily_entry_cap_mode": "fixed_cap",
                "daily_entry_count_is_blocking": True,
                "active_trade_gate": "absolute_max_new_entries_per_day",
            }
        )

    return result
