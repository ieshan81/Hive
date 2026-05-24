"""Cost-aware fill model for research backtests — no fantasy mid-price fills."""

from __future__ import annotations

from typing import Any


def symbol_tier(symbol: str, config: dict) -> str:
    sym = symbol.upper().replace("/", "")
    rules = (config.get("symbol_tiers") or {}).get("tier_rules") or []
    for rule in rules:
        pat = (rule.get("pattern") or "").upper()
        if pat and pat in sym:
            return rule.get("tier", "TIER_ALT")
    if "DOGE" in sym or "SHIB" in sym:
        return "TIER_MEME_SUPPORTED"
    if sym.startswith("BTC") or sym.startswith("ETH"):
        return "TIER_MAJOR"
    return "TIER_ALT"


def spread_pct_for_tier(tier: str, config: dict) -> float:
    cost = config.get("cost") or {}
    if tier in ("TIER_MAJOR",):
        return float(cost.get("slippage_buffer_major_pct", 0.10)) / 100.0
    if tier in ("TIER_MEME_SUPPORTED", "TIER_MEME"):
        return float(cost.get("slippage_buffer_meme_pct", 0.30)) / 100.0
    return float(cost.get("slippage_buffer_alt_pct", 0.20)) / 100.0


def round_trip_cost_pct(symbol: str, config: dict) -> dict[str, Any]:
    cost = config.get("cost") or {}
    tier = symbol_tier(symbol, config)
    spread = spread_pct_for_tier(tier, config)
    fee = float(cost.get("taker_fee_pct", 0.25)) / 100.0
    slip = spread
    total = (spread + slip + fee) * 2
    return {
        "tier": tier,
        "spread_pct": spread,
        "slippage_pct": slip,
        "fee_pct": fee,
        "round_trip_pct": total,
        "estimated_spread": True,
    }


def entry_exit_prices(
    mid: float,
    side: str,
    symbol: str,
    config: dict,
) -> dict[str, float]:
    """Conservative bid/ask model from mid when no L2 data."""
    if mid <= 0:
        return {"entry": 0.0, "exit": 0.0, "spread_pct": 0.0}
    cm = round_trip_cost_pct(symbol, config)
    half_spread = cm["spread_pct"] / 2.0
    if side == "buy":
        entry = mid * (1 + half_spread + cm["slippage_pct"])
        exit_mid = mid
        exit = exit_mid * (1 - half_spread - cm["slippage_pct"])
    else:
        entry = mid * (1 - half_spread - cm["slippage_pct"])
        exit = mid * (1 + half_spread + cm["slippage_pct"])
    return {"entry": entry, "exit": exit, "spread_pct": cm["spread_pct"]}


def apply_trade_return(gross_return: float, symbol: str, config: dict) -> float:
    rt = round_trip_cost_pct(symbol, config)
    return gross_return - rt["round_trip_pct"]
