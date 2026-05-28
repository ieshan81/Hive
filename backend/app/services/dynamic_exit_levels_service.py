"""Dynamic stop/target/trailing levels for push-pull paper trades.

This service is deterministic. It never submits orders and never grants trade
permission; it only converts price action, spread, and signal quality into the
exit levels used by the cage and UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.services.atr_sizing import compute_atr_from_bars
from app.services.engine_config import cfg_get


@dataclass
class DynamicExitLevels:
    side: str
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    trailing_stop: float
    invalidation_price: float
    stop_distance: float
    target_distance: float
    trailing_distance: float
    risk_reward: float
    expected_move_pct: float
    atr: Optional[float]
    atr_period: int
    volatility_regime: str
    bars: dict[str, dict[str, Any]]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "trailing_stop": self.trailing_stop,
            "invalidation_price": self.invalidation_price,
            "stop_distance": self.stop_distance,
            "target_distance": self.target_distance,
            "trailing_distance": self.trailing_distance,
            "risk_reward": self.risk_reward,
            "expected_move_pct": self.expected_move_pct,
            "atr": self.atr,
            "atr_period": self.atr_period,
            "volatility_regime": self.volatility_regime,
            "bars": self.bars,
            "evidence": self.evidence,
        }


def _positive(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return default
    return val if val > 0 else default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _score_0_1(value: Any) -> float:
    val = _positive(value, 0.0)
    if val > 1.5:
        val = val / 100.0
    return _clamp(val, 0.0, 1.0)


def _spread_pct(quote: Optional[dict[str, Any]]) -> float:
    quote = quote or {}
    spread_pct = quote.get("spread_pct")
    if spread_pct is not None:
        val = _positive(spread_pct, 0.0)
        return val / 100.0 if val > 1 else val
    bid = _positive(quote.get("bid"), 0.0)
    ask = _positive(quote.get("ask"), 0.0)
    mid = _positive(quote.get("mid"), 0.0) or ((bid + ask) / 2.0 if bid and ask else 0.0)
    if bid and ask and mid:
        return max(0.0, (ask - bid) / mid)
    return 0.0


def _volatility_regime(atr_pct: float) -> str:
    if atr_pct >= 0.03:
        return "high"
    if atr_pct >= 0.012:
        return "normal"
    if atr_pct > 0:
        return "calm"
    return "unknown"


def _round_price(value: float, entry_price: float) -> float:
    if entry_price >= 100:
        ndigits = 2
    elif entry_price >= 1:
        ndigits = 4
    else:
        ndigits = 8
    return round(value, ndigits)


def compute_dynamic_exit_levels(
    config: dict[str, Any],
    *,
    symbol: str,
    side: str,
    entry_price: float,
    current_price: Optional[float] = None,
    bars: Optional[list[dict[str, Any]]] = None,
    quote: Optional[dict[str, Any]] = None,
    signal_meta: Optional[dict[str, Any]] = None,
    tier: Optional[str] = None,
) -> DynamicExitLevels:
    """Build side-correct exit levels from current market context.

    For long paper entries, side is "buy": stop below entry, target above entry.
    For short-style scoring support, side is "sell": stop above entry, target
    below entry. The live product still blocks naked sell entries elsewhere.
    """

    entry = _positive(entry_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")
    current = _positive(current_price, entry)
    bars = bars or []
    signal_meta = signal_meta or {}
    side_l = str(side or "buy").lower()
    is_buy = side_l != "sell"
    direction = 1.0 if is_buy else -1.0

    pp = config.get("push_pull") or {}
    cpp = config.get("crypto_push_pull") or {}
    dyn = pp.get("dynamic_exits") or {}

    atr_period = int(dyn.get("atr_period") or pp.get("atr_period") or cfg_get(config, "risk.atr_period", 14))
    atr = compute_atr_from_bars(bars, atr_period)
    fallback_stop_pct = float(dyn.get("fallback_stop_pct") or cpp.get("stop_loss_pct", 0.02))
    fallback_atr = entry * fallback_stop_pct
    atr_value = _positive(atr, fallback_atr)
    atr_pct = atr_value / entry if entry else 0.0
    regime = _volatility_regime(atr_pct if atr is not None else 0.0)

    spread = _spread_pct(quote)
    spread_bps = spread * 10000.0
    spread_abs = entry * spread

    components = signal_meta.get("score_components") if isinstance(signal_meta.get("score_components"), dict) else {}
    quality = _score_0_1(
        signal_meta.get("trade_quality_score")
        or signal_meta.get("quality")
        or components.get("trade_quality_0_100")
    )
    push = _score_0_1(signal_meta.get("push_score") or signal_meta.get("push_score_0_100"))
    edge_bps = _positive(signal_meta.get("edge_after_cost_bps"), 0.0)
    sentiment_adj = float(signal_meta.get("sentiment_adjustment_pct") or 0.0)
    pump_risk = bool(signal_meta.get("pump_dump_risk") or signal_meta.get("manipulation_risk") == "high")

    atr_mult = float(dyn.get("atr_stop_multiplier") or pp.get("atr_stop_multiplier", 2.0))
    min_stop_bps = float(dyn.get("min_stop_bps", 35.0))
    max_stop_bps = float(dyn.get("max_stop_bps", 500.0))
    spread_mult = float(dyn.get("spread_cushion_multiplier", 3.0))
    min_stop_distance = entry * max(min_stop_bps, spread_bps * spread_mult + 5.0) / 10000.0
    raw_stop_distance = max(atr_value * atr_mult, min_stop_distance, spread_abs * spread_mult)

    quality_stop_factor = 1.0 + ((quality - 0.5) * 0.25)
    if pump_risk:
        quality_stop_factor *= 0.75
    stop_distance = raw_stop_distance * _clamp(quality_stop_factor, 0.75, 1.25)
    stop_distance = _clamp(stop_distance, min_stop_distance, entry * (max_stop_bps / 10000.0))

    quick_scalp = bool(dyn.get("quick_scalp_enabled", True))
    base_r_default = 0.9 if quick_scalp else 1.35
    max_r_default = 1.8 if quick_scalp else 2.75
    base_r = float(dyn.get("base_target_r_multiple", base_r_default))
    max_r = float(dyn.get("max_target_r_multiple", max_r_default))
    r_multiple = base_r + (quality * 0.65) + (push * 0.35) + min(edge_bps / 1000.0, 0.35)
    r_multiple += _clamp(sentiment_adj / 100.0, -0.10, 0.10)
    if pump_risk:
        r_multiple = min(r_multiple, base_r)
    r_multiple = _clamp(r_multiple, base_r, max_r)

    profit_target_bps = float(dyn.get("profit_target_bps") or pp.get("profit_target_bps", 120.0 if quick_scalp else 300.0))
    if quick_scalp:
        tier_name = str(tier or "").upper()
        if "MAJOR" in tier_name:
            tier_floor = float(dyn.get("min_target_bps_major", 55.0))
        elif "MEME" in tier_name:
            tier_floor = float(dyn.get("min_target_bps_meme", 100.0))
        else:
            tier_floor = float(dyn.get("min_target_bps_alt", 80.0))
        spread_floor = (spread_bps * float(dyn.get("target_spread_multiplier", 4.0))) + 15.0
        max_quick_target = float(dyn.get("max_quick_target_bps", 180.0))
        profit_target_bps = min(max_quick_target, max(profit_target_bps, tier_floor, spread_floor))
    target_floor = entry * (profit_target_bps / 10000.0)
    target_distance = max(stop_distance * r_multiple, target_floor, atr_value * (1.0 + push))

    trailing_bps = float(dyn.get("trailing_giveback_bps") or pp.get("trailing_giveback_bps", 45.0 if quick_scalp else 100.0))
    trailing_distance = max(entry * (trailing_bps / 10000.0), atr_value * 0.75, spread_abs * 2.0)

    stop_loss = entry - (direction * stop_distance)
    take_profit = entry + (direction * target_distance)
    invalidation_distance = max(stop_distance * 0.55, min_stop_distance)
    invalidation = entry - (direction * invalidation_distance)

    favorable_move = (current - entry) * direction
    if favorable_move > stop_distance * 0.5:
        trail_candidate = current - (direction * trailing_distance)
        if is_buy:
            trailing_stop = max(stop_loss, trail_candidate)
        else:
            trailing_stop = min(stop_loss, trail_candidate)
    else:
        trailing_stop = stop_loss

    risk_reward = target_distance / stop_distance if stop_distance > 0 else 0.0
    expected_move_pct = (target_distance / entry) * 100.0
    stop_bps = (stop_distance / entry) * 10000.0
    target_bps = (target_distance / entry) * 10000.0
    trail_bps = (trailing_distance / entry) * 10000.0

    stop_loss = _round_price(stop_loss, entry)
    take_profit = _round_price(take_profit, entry)
    trailing_stop = _round_price(trailing_stop, entry)
    invalidation = _round_price(invalidation, entry)

    bars_out = {
        "entry": {
            "label": "Entry",
            "price": _round_price(entry, entry),
            "role": "entry",
            "reason": "Current paper signal reference price.",
        },
        "stop_loss": {
            "label": "Stop loss",
            "price": stop_loss,
            "role": "risk_floor",
            "distance_bps": round(stop_bps, 2),
            "condition": "Exit the position when price crosses this level.",
            "reason": "Built from ATR, spread cushion, and signal quality.",
        },
        "take_profit": {
            "label": "Take profit",
            "price": take_profit,
            "role": "profit_target",
            "distance_bps": round(target_bps, 2),
            "condition": "Exit the position when price reaches this target.",
            "reason": "Target is a dynamic R-multiple adjusted by push quality and edge.",
        },
        "trailing_stop": {
            "label": "Trailing stop",
            "price": trailing_stop,
            "role": "profit_protection",
            "distance_bps": round(trail_bps, 2),
            "condition": "After favorable movement, pull the exit bar behind price.",
            "reason": "Uses ATR, configured giveback, and spread cushion.",
        },
        "invalidation": {
            "label": "Invalidation",
            "price": invalidation,
            "role": "setup_invalidated",
            "condition": "Push-pull thesis weakens before the full hard stop.",
            "reason": "Midway failure level between entry and the hard stop.",
        },
    }

    evidence = {
        "symbol": symbol,
        "tier": tier,
        "formula": "dynamic_atr_spread_quality_stop_target_v1",
        "atr_source": "bars" if atr is not None else "fallback_stop_pct",
        "atr": atr,
        "atr_period": atr_period,
        "atr_pct": round(atr_pct, 6),
        "volatility_regime": regime,
        "spread_pct": spread,
        "spread_bps": round(spread_bps, 2),
        "quality": round(quality, 4),
        "push": round(push, 4),
        "edge_after_cost_bps": round(edge_bps, 2),
        "sentiment_adjustment_pct": sentiment_adj,
        "pump_dump_risk": pump_risk,
        "quick_scalp_enabled": quick_scalp,
        "r_multiple": round(r_multiple, 4),
        "stop_bps": round(stop_bps, 2),
        "profit_target_floor_bps": round(profit_target_bps, 2),
        "target_bps": round(target_bps, 2),
        "trailing_bps": round(trail_bps, 2),
        "bars_count": len(bars),
    }

    return DynamicExitLevels(
        side=side_l,
        entry_price=_round_price(entry, entry),
        current_price=_round_price(current, entry),
        stop_loss=stop_loss,
        take_profit=take_profit,
        trailing_stop=trailing_stop,
        invalidation_price=invalidation,
        stop_distance=round(stop_distance, 10),
        target_distance=round(target_distance, 10),
        trailing_distance=round(trailing_distance, 10),
        risk_reward=round(risk_reward, 4),
        expected_move_pct=round(expected_move_pct, 4),
        atr=round(atr, 10) if atr is not None else None,
        atr_period=atr_period,
        volatility_regime=regime,
        bars=bars_out,
        evidence=evidence,
    )


def exit_trigger_for_long(
    *,
    current_price: float,
    levels: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Return deterministic long-position exit trigger, if any."""

    price = _positive(current_price)
    if price <= 0:
        return None
    stop = _positive(levels.get("stop_loss"), 0.0)
    target = _positive(levels.get("take_profit"), 0.0)
    trail = _positive(levels.get("trailing_stop"), 0.0)
    invalidation = _positive(levels.get("invalidation_price"), 0.0)
    if target and price >= target:
        return {
            "action": "exit_recommended",
            "reason": "dynamic_take_profit_hit",
            "trigger_price": target,
            "current_price": price,
        }
    if stop and price <= stop:
        return {
            "action": "exit_recommended",
            "reason": "dynamic_stop_loss_hit",
            "trigger_price": stop,
            "current_price": price,
        }
    if trail and price <= trail:
        return {
            "action": "exit_recommended",
            "reason": "dynamic_trailing_stop_hit",
            "trigger_price": trail,
            "current_price": price,
        }
    if invalidation and price <= invalidation:
        return {
            "action": "exit_recommended",
            "reason": "dynamic_invalidation_hit",
            "trigger_price": invalidation,
            "current_price": price,
        }
    return None
