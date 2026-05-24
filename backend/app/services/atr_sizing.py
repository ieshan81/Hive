"""ATR-based stop distance and position sizing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from app.services.engine_config import cfg_get, risk_pct
from app.services.symbol_tier_service import TIER_MEME_SUPPORTED, TIER_MAJOR


@dataclass
class AtrSizingResult:
    passed: bool
    block_reason_code: Optional[str]
    human_reason: Optional[str]
    atr14: Optional[float]
    stop_distance: Optional[float]
    stop_loss_price: Optional[float]
    position_qty: Optional[float]
    position_notional: Optional[float]
    risk_dollars: Optional[float]
    evidence: dict[str, Any]


def _k_atr(config: dict, tier: str) -> float:
    if tier == TIER_MEME_SUPPORTED:
        return float(cfg_get(config, "risk.k_atr_meme", 2.5))
    if tier == TIER_MAJOR or "MAJOR" in tier:
        return float(cfg_get(config, "risk.k_atr_major", 2.0))
    return float(cfg_get(config, "risk.k_atr_alt", 2.0))


def compute_atr_from_bars(bars: list[dict], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(-period, 0):
        h = bars[i]["high"]
        l = bars[i]["low"]
        prev_c = bars[i - 1]["close"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


def evaluate_atr_sizing(
    config: dict,
    *,
    equity: float,
    entry_price: float,
    side: str,
    tier: str,
    bars: list[dict],
    spread_pct: Optional[float],
    crypto_bucket_remaining: float,
    buying_power: float,
    reserve_cash_pct: float,
    current_symbol_exposure: float = 0.0,
    total_crypto_exposure: float = 0.0,
) -> AtrSizingResult:
    period = int(cfg_get(config, "risk.atr_period", 14))
    atr = compute_atr_from_bars(bars, period)
    evidence: dict[str, Any] = {"atr_period": period, "tier": tier, "entry_price": entry_price}

    if atr is None or atr <= 0:
        evidence["missing"] = ["atr14"]
        return AtrSizingResult(
            passed=False,
            block_reason_code="ATR_DATA_MISSING",
            human_reason="ATR data unavailable — cannot size position",
            atr14=None,
            stop_distance=None,
            stop_loss_price=None,
            position_qty=None,
            position_notional=None,
            risk_dollars=None,
            evidence=evidence,
        )

    if not math.isfinite(atr):
        return AtrSizingResult(
            passed=False,
            block_reason_code="INVALID_ATR",
            human_reason="Invalid ATR value",
            atr14=atr,
            stop_distance=None,
            stop_loss_price=None,
            position_qty=None,
            position_notional=None,
            risk_dollars=None,
            evidence=evidence,
        )

    k = _k_atr(config, tier)
    stop_distance = k * atr
    evidence["atr14"] = atr
    evidence["k_atr"] = k
    evidence["stop_distance"] = stop_distance

    if stop_distance <= 0:
        return AtrSizingResult(
            passed=False,
            block_reason_code="INVALID_STOP_DISTANCE",
            human_reason="Stop distance invalid",
            atr14=atr,
            stop_distance=stop_distance,
            stop_loss_price=None,
            position_qty=None,
            position_notional=None,
            risk_dollars=None,
            evidence=evidence,
        )

    taker = float(cfg_get(config, "cost.taker_fee_pct", 0.25))
    slip_key = "slippage_buffer_meme_pct" if tier == TIER_MEME_SUPPORTED else "slippage_buffer_alt_pct"
    slippage = float(cfg_get(config, f"cost.{slip_key}", 0.10))
    spread_cost = (float(spread_pct or 0) * 100) if spread_pct and spread_pct < 1 else float(spread_pct or 0)
    round_trip = (2 * taker) + spread_cost + slippage
    floor_mult = float(cfg_get(config, "risk.stop_cost_floor_multiplier", 2.0))
    min_stop_pct = (round_trip * floor_mult) / 100.0 * entry_price
    if stop_distance < min_stop_pct:
        return AtrSizingResult(
            passed=False,
            block_reason_code="STOP_DISTANCE_BELOW_COST_FLOOR",
            human_reason=f"ATR stop distance below cost floor ({min_stop_pct:.4f})",
            atr14=atr,
            stop_distance=stop_distance,
            stop_loss_price=None,
            position_qty=None,
            position_notional=None,
            risk_dollars=None,
            evidence={**evidence, "min_stop_distance": min_stop_pct, "round_trip_cost_pct": round_trip},
        )

    is_buy = side.lower() == "buy"
    stop_loss = entry_price - stop_distance if is_buy else entry_price + stop_distance
    rp = risk_pct(config)
    risk_dollars = equity * rp
    position_notional = risk_dollars / (stop_distance / entry_price) if entry_price > 0 else 0
    position_qty = position_notional / entry_price if entry_price > 0 else 0

    max_sym_pct = float(cfg_get(config, "risk.max_exposure_per_symbol_pct", 15.0)) / 100.0
    max_total_pct = float(cfg_get(config, "risk.max_total_crypto_exposure_pct", 40.0)) / 100.0
    sym_cap = equity * max_sym_pct - current_symbol_exposure
    total_cap = equity * max_total_pct - total_crypto_exposure
    reserve = equity * (reserve_cash_pct / 100.0)
    bp_cap = max(0.0, buying_power - reserve)

    position_notional = min(position_notional, sym_cap, total_cap, crypto_bucket_remaining, bp_cap)
    position_qty = position_notional / entry_price if entry_price > 0 else 0

    min_notional = float(cfg_get(config, "min_order_notional_usd", 1.0))
    evidence.update(
        {
            "risk_pct": rp,
            "risk_dollars": risk_dollars,
            "position_notional": position_notional,
            "position_qty": position_qty,
            "stop_loss_price": stop_loss,
        }
    )

    if position_notional < min_notional:
        return AtrSizingResult(
            passed=False,
            block_reason_code="NOTIONAL_TOO_SMALL",
            human_reason=f"Position notional ${position_notional:.2f} below minimum ${min_notional:.2f}",
            atr14=atr,
            stop_distance=stop_distance,
            stop_loss_price=stop_loss,
            position_qty=position_qty,
            position_notional=position_notional,
            risk_dollars=risk_dollars,
            evidence=evidence,
        )
    if position_qty <= 0:
        return AtrSizingResult(
            passed=False,
            block_reason_code="POSITION_SIZE_TOO_SMALL",
            human_reason="Computed position size is zero",
            atr14=atr,
            stop_distance=stop_distance,
            stop_loss_price=stop_loss,
            position_qty=position_qty,
            position_notional=position_notional,
            risk_dollars=risk_dollars,
            evidence=evidence,
        )

    return AtrSizingResult(
        passed=True,
        block_reason_code=None,
        human_reason=None,
        atr14=atr,
        stop_distance=stop_distance,
        stop_loss_price=stop_loss,
        position_qty=position_qty,
        position_notional=position_notional,
        risk_dollars=risk_dollars,
        evidence=evidence,
    )
