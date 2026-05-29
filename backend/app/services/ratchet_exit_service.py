"""Paper ratchet exits — buy with floors that only move up, sell on giveback.

Principle: enter paper longs with dynamic SL/TP, then as price rises arm a
ratchet floor under the peak. The floor never moves down; a break below it exits.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.engine_config import cfg_get


def paper_ratchet_enabled(config: dict) -> bool:
    pr = config.get("paper_ratchet") or {}
    if pr.get("enabled") is not None:
        return bool(pr.get("enabled"))
    return bool(cfg_get(config, "paper_ratchet.enabled", False))


def ratchet_cfg(config: dict) -> dict[str, Any]:
    return dict(config.get("paper_ratchet") or {})


def relax_entry_stale_bar(config: dict) -> bool:
    if not paper_ratchet_enabled(config):
        return False
    return bool(ratchet_cfg(config).get("relax_entry_stale_bar", True))


def entry_min_bars(config: dict) -> int:
    return int(ratchet_cfg(config).get("relax_entry_min_bars", 8))


def update_ratchet_state(
    config: dict,
    *,
    entry_price: float,
    current_price: float,
    state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Advance high-water mark and ratchet floor (long only)."""
    cfg = ratchet_cfg(config)
    entry = float(entry_price)
    current = float(current_price)
    if entry <= 0 or current <= 0:
        return dict(state or {})

    giveback_bps = float(cfg.get("giveback_bps", 40.0))
    arm_bps = float(cfg.get("arm_trailing_after_profit_bps", 25.0))
    initial_stop_pct = float(cfg.get("initial_stop_pct", 0.02))

    prev = dict(state or {})
    peak = max(float(prev.get("peak_price") or entry), current)
    hard_stop = entry * (1.0 - initial_stop_pct)
    prev_floor = float(prev.get("ratchet_floor") or hard_stop)
    armed = bool(prev.get("ratchet_armed"))

    profit_bps = ((current - entry) / entry) * 10000.0
    if profit_bps >= arm_bps:
        armed = True

    if armed:
        candidate = peak * (1.0 - giveback_bps / 10000.0)
        floor = max(prev_floor, candidate, hard_stop)
    else:
        floor = max(prev_floor, hard_stop)

    return {
        "peak_price": round(peak, 10),
        "ratchet_floor": round(floor, 10),
        "ratchet_armed": armed,
        "profit_bps": round(profit_bps, 2),
        "giveback_bps": giveback_bps,
        "arm_after_profit_bps": arm_bps,
        "initial_stop": round(hard_stop, 10),
        "mode": "paper_ratchet_v1",
    }


def merge_ratchet_into_levels(levels: dict[str, Any], ratchet: dict[str, Any]) -> dict[str, Any]:
    """Overlay ratchet floor as the active trailing stop for UI and monitors."""
    out = dict(levels or {})
    floor = ratchet.get("ratchet_floor")
    if floor is None:
        return out
    out["ratchet_floor"] = floor
    out["ratchet_armed"] = ratchet.get("ratchet_armed")
    out["peak_price"] = ratchet.get("peak_price")
    trail = float(out.get("trailing_stop") or 0)
    if trail <= 0 or float(floor) > trail:
        out["trailing_stop"] = floor
    stop = float(out.get("stop_loss") or 0)
    if stop <= 0 or float(floor) > stop:
        out["stop_loss"] = max(float(ratchet.get("initial_stop") or 0), float(floor))
    return out


def exit_trigger_ratchet_long(
    *,
    current_price: float,
    levels: dict[str, Any],
    ratchet: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Check ratchet floor and standard dynamic levels."""
    from app.services.dynamic_exit_levels_service import exit_trigger_for_long

    price = float(current_price)
    floor = float(ratchet.get("ratchet_floor") or 0)
    armed = bool(ratchet.get("ratchet_armed"))
    hard = float(ratchet.get("initial_stop") or levels.get("stop_loss") or 0)

    if hard > 0 and price <= hard:
        return {
            "action": "exit_recommended",
            "reason": "ratchet_initial_stop_hit",
            "trigger_price": hard,
            "current_price": price,
        }
    if armed and floor > 0 and price <= floor:
        return {
            "action": "exit_recommended",
            "reason": "ratchet_floor_hit",
            "trigger_price": floor,
            "current_price": price,
            "peak_price": ratchet.get("peak_price"),
        }
    return exit_trigger_for_long(current_price=price, levels=levels)


def buy_low_pullback_ok(bars: list[dict], *, pullback_bps: float = 80.0) -> bool:
    """True when last close is below recent range high by pullback_bps (soft buy-low)."""
    if len(bars) < 12:
        return True
    closes = [float(b.get("close") or 0) for b in bars[-24:] if b.get("close")]
    if not closes:
        return True
    recent_high = max(closes)
    last = closes[-1]
    if recent_high <= 0:
        return True
    drop_bps = ((recent_high - last) / recent_high) * 10000.0
    return drop_bps >= pullback_bps * 0.35


def apply_paper_ratchet_entry(
    row: dict[str, Any],
    config: dict,
    *,
    bars: list[dict],
) -> dict[str, Any]:
    """Promote paper entry when ratchet mode on: bars + exit bands, ignore stale_bar."""
    if not paper_ratchet_enabled(config):
        return row
    if row.get("entry_allowed"):
        return row
    levels = row.get("dynamic_exit_levels") or {}
    if levels.get("status") == "unavailable":
        return row
    min_bars = entry_min_bars(config)
    if len(bars) < min_bars:
        return row
    required = ("stop_loss", "take_profit", "trailing_stop")
    if not all(levels.get(k) is not None for k in required):
        return row

    cfg = ratchet_cfg(config)
    pullback_bps = float(cfg.get("buy_low_pullback_bps", 80.0))
    if not buy_low_pullback_ok(bars, pullback_bps=pullback_bps):
        return row

    reason = str(row.get("no_trade_reason") or "strict_gate")
    out = dict(row)
    out["entry_allowed"] = True
    out["paper_ratchet_entry"] = True
    out["no_trade_reason"] = None
    out["soft_concerns"] = list(dict.fromkeys((out.get("soft_concerns") or []) + [reason, "paper_ratchet"]))
    out["thesis"] = (
        "Paper ratchet: enter on pullback; ratchet floor will rise with price and exit on giveback."
    )
    tq = float(out.get("trade_quality_score") or 0)
    out["trade_quality_score"] = max(tq, 0.42)
    return out
