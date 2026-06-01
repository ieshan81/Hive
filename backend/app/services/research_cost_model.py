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


COST_MODEL_VERSION = "v2_components_no_double_count"

# Conservative per-tier defaults (bps), operator-tunable via config["cost"].*. These replace
# the legacy model that set slippage == spread and multiplied (spread+slip+fee) by 2, which
# double-counted the spread. Components are now explicit per side.
_DEFAULT_SPREAD_BPS = {"TIER_MAJOR": 8.0, "TIER_ALT": 20.0, "TIER_MEME_SUPPORTED": 40.0, "TIER_MEME": 40.0}
_DEFAULT_SLIPPAGE_BPS = {"TIER_MAJOR": 4.0, "TIER_ALT": 10.0, "TIER_MEME_SUPPORTED": 25.0, "TIER_MEME": 25.0}
_DEFAULT_FEE_BPS_PER_SIDE = 10.0
_DEFAULT_MULT = 1.0
_DEFAULT_FLOOR_BPS = 8.0
_DEFAULT_CAP_BPS = 150.0


def _tier_bps(config: dict, key: str, default_map: dict, tier: str) -> float:
    table = ((config or {}).get("cost") or {}).get(key) or {}
    if isinstance(table, dict) and tier in table:
        try:
            return float(table[tier])
        except (TypeError, ValueError):
            pass
    return float(default_map.get(tier, default_map.get("TIER_ALT", 20.0)))


def _fee_bps_per_side(config: dict) -> float:
    cost = (config or {}).get("cost") or {}
    if "default_fee_bps" in cost:
        try:
            return float(cost["default_fee_bps"])
        except (TypeError, ValueError):
            pass
    if "taker_fee_pct" in cost:  # legacy key was a percent (0.25 == 0.25%)
        try:
            return float(cost["taker_fee_pct"]) * 100.0
        except (TypeError, ValueError):
            pass
    return _DEFAULT_FEE_BPS_PER_SIDE


def spread_pct_for_tier(tier: str, config: dict) -> float:
    """Full spread fraction for the tier (used by the bid/ask fill model)."""
    return _tier_bps(config, "default_spread_bps_by_tier", _DEFAULT_SPREAD_BPS, tier) / 10000.0


def round_trip_cost_pct(symbol: str, config: dict) -> dict[str, Any]:
    """Round-trip cost as explicit named components — NO double-counting.

    Cross the spread once round-trip (half each side), slippage each side, fee each side:
      round_trip = (spread/2 + spread/2) + (slip + slip) + (fee + fee)
    """
    cost = (config or {}).get("cost") or {}
    tier = symbol_tier(symbol, config)
    spread_bps = _tier_bps(config, "default_spread_bps_by_tier", _DEFAULT_SPREAD_BPS, tier)
    slip_bps = _tier_bps(config, "default_slippage_bps_by_tier", _DEFAULT_SLIPPAGE_BPS, tier)
    fee_bps = _fee_bps_per_side(config)
    mult = float(cost.get("conservative_cost_multiplier", _DEFAULT_MULT) or _DEFAULT_MULT)
    floor_bps = float(cost.get("min_cost_floor_bps", _DEFAULT_FLOOR_BPS))
    cap_bps = float(cost.get("max_cost_cap_bps", _DEFAULT_CAP_BPS))

    entry_spread, exit_spread = spread_bps / 2.0, spread_bps / 2.0
    entry_slip, exit_slip = slip_bps, slip_bps
    entry_fee, exit_fee = fee_bps, fee_bps
    rt_bps = (entry_spread + exit_spread + entry_slip + exit_slip + entry_fee + exit_fee) * mult
    rt_bps = max(floor_bps, min(cap_bps, rt_bps))
    return {
        "tier": tier,
        "spread_pct": spread_bps / 10000.0,
        "slippage_pct": (entry_slip + exit_slip) / 10000.0,
        "fee_pct": (entry_fee + exit_fee) / 10000.0,
        "round_trip_pct": rt_bps / 10000.0,
        "spread_bps": round(spread_bps, 3),
        "slippage_bps": round(entry_slip + exit_slip, 3),
        "fee_bps": round(entry_fee + exit_fee, 3),
        "round_trip_bps": round(rt_bps, 3),
        "estimated_spread": True,
        "cost_model_version": COST_MODEL_VERSION,
        "components": {
            "entry_spread_bps": entry_spread,
            "exit_spread_bps": exit_spread,
            "entry_slippage_bps": entry_slip,
            "exit_slippage_bps": exit_slip,
            "entry_fee_bps": entry_fee,
            "exit_fee_bps": exit_fee,
            "conservative_multiplier": mult,
            "floor_bps": floor_bps,
            "cap_bps": cap_bps,
        },
    }


def legacy_round_trip_cost_pct(symbol: str, config: dict) -> dict[str, Any]:
    """Pre-fix (double-counting) model — kept ONLY for old-vs-new shadow comparison."""
    cost = (config or {}).get("cost") or {}
    tier = symbol_tier(symbol, config)
    if tier in ("TIER_MAJOR",):
        spread = float(cost.get("slippage_buffer_major_pct", 0.10)) / 100.0
    elif tier in ("TIER_MEME_SUPPORTED", "TIER_MEME"):
        spread = float(cost.get("slippage_buffer_meme_pct", 0.30)) / 100.0
    else:
        spread = float(cost.get("slippage_buffer_alt_pct", 0.20)) / 100.0
    fee = float(cost.get("taker_fee_pct", 0.25)) / 100.0
    slip = spread
    total = (spread + slip + fee) * 2  # double-counts spread (slip==spread) and x2
    return {"tier": tier, "round_trip_pct": total, "round_trip_bps": total * 10000.0}


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
