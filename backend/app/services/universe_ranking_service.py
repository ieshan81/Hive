"""
Universe Radar — Full Pipeline (Caged Hive Quant spec, DOMAIN 1).

Pipeline: Available → Cached → Fresh Data → Eligible → Ranked → Execution Shortlist

Ranking formula (per cycle):
    universe_rank_score = (
        0.25 * liquidity_pct       # dollar volume percentile within universe
      + 0.15 * spread_pct_inv      # (1 - spread/price) percentile
      + 0.20 * volume_spike_pct    # 1m vol / 20m_avg_vol percentile
      + 0.15 * atr_pct             # 14-bar ATR / price percentile (Wilder 1978)
      + 0.15 * freshness_pct       # 1 - bar_age_seconds / max_age (clamped)
      + 0.10 * cost_efficiency     # 1 - (fees+spread) / expected_move
    )

Symbols below min_rank=0.40 are dropped before the candidate stage.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any, Optional

from app.services.push_pull_scorer import compute_atr, DEFAULT_TAKER_FEE_BPS


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

MIN_RANK_SCORE = 0.40
MAX_EXECUTION_SHORTLIST = 10
MAX_BAR_AGE_SECONDS = 120.0
DEFAULT_SPREAD_MAX_BPS = 50.0  # symbols above this are spread-ineligible


# ──────────────────────────────────────────────────────────────
# Percentile helpers
# ──────────────────────────────────────────────────────────────

def _percentile_rank(value: float, all_values: list[float]) -> float:
    """Returns 0..1 — fraction of values that are strictly below `value`."""
    if not all_values:
        return 0.5
    below = sum(1 for v in all_values if v < value)
    return below / len(all_values)


def _safe_divide(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


# ──────────────────────────────────────────────────────────────
# Per-symbol raw metrics extraction
# ──────────────────────────────────────────────────────────────

def extract_symbol_metrics(
    symbol: str,
    bars_1m: list[dict],
    quote: dict,
    *,
    bar_max_age_s: float = MAX_BAR_AGE_SECONDS,
    taker_fee_bps: float = DEFAULT_TAKER_FEE_BPS,
) -> dict[str, Any]:
    """
    Compute the raw (un-ranked) numeric metrics for one symbol.
    Returns dict ready to be fed into rank_universe().
    """
    if not bars_1m:
        return {
            "symbol": symbol,
            "dollar_volume": 0.0,
            "spread_bps": 9999.0,
            "volume_spike_ratio": 0.0,
            "atr_over_price": 0.0,
            "freshness": 0.0,
            "cost_efficiency": 0.0,
            "eligible": False,
            "ineligible_reason": "no_bars",
        }

    latest = bars_1m[-1]
    price = latest["close"] or 1.0
    vol_latest = latest.get("volume", 0.0)

    # Dollar volume (latest bar)
    dollar_volume = vol_latest * price

    # Spread in bps
    bid_raw = quote.get("bid")
    ask_raw = quote.get("ask")
    bid = float(bid_raw) if bid_raw is not None else price * 0.998
    ask = float(ask_raw) if ask_raw is not None else price * 1.002
    mid = (bid + ask) / 2.0 or price
    spread_bps = ((ask - bid) / mid) * 10_000 if mid > 0 else 9999.0

    # Volume spike ratio — 1m vol / 20m avg vol
    vol_window = [b.get("volume", 0.0) for b in bars_1m[-21:-1]]
    vol_sma20 = sum(vol_window) / max(len(vol_window), 1)
    volume_spike_ratio = _safe_divide(vol_latest, vol_sma20, 1.0)

    # ATR / price (Wilder 14-bar)
    atr = compute_atr(bars_1m[-15:], 14) if len(bars_1m) >= 15 else (latest["high"] - latest["low"])
    atr_over_price = _safe_divide(atr, price)

    # Bar freshness
    bar_ts_raw = latest.get("received_at_local") or latest.get("timestamp")
    if bar_ts_raw:
        try:
            if isinstance(bar_ts_raw, str):
                ts = datetime.fromisoformat(bar_ts_raw.replace("Z", "+00:00"))
            else:
                ts = bar_ts_raw
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=None)
                age_s = (datetime.utcnow() - ts).total_seconds()
            else:
                age_s = (datetime.now(tz=ts.tzinfo) - ts).total_seconds()
        except Exception:
            age_s = bar_max_age_s
    else:
        age_s = 0.0  # assume fresh if no timestamp
    freshness = max(0.0, min(1.0, 1.0 - age_s / bar_max_age_s))

    # Cost efficiency — 1 - (fees + spread) / expected_move
    roundtrip_cost_bps = (taker_fee_bps * 2) + spread_bps + 8.0  # +8 slippage buffer
    expected_move_bps = (0.5 * atr / max(price, 1e-8)) * 10_000  # 0.5 ATR continuation
    cost_efficiency = max(0.0, 1.0 - _safe_divide(roundtrip_cost_bps, max(expected_move_bps, 1.0), 1.0))

    # Eligibility pre-screen
    eligible = True
    ineligible_reason = None
    if spread_bps > DEFAULT_SPREAD_MAX_BPS:
        eligible = False
        ineligible_reason = "spread_too_wide"
    elif freshness < 0.1:
        eligible = False
        ineligible_reason = "bar_stale"
    elif price <= 0:
        eligible = False
        ineligible_reason = "zero_price"

    return {
        "symbol": symbol,
        "price": price,
        "dollar_volume": dollar_volume,
        "spread_bps": spread_bps,
        "volume_spike_ratio": volume_spike_ratio,
        "atr_over_price": atr_over_price,
        "freshness": freshness,
        "cost_efficiency": cost_efficiency,
        "bar_age_seconds": age_s,
        "atr": atr,
        "eligible": eligible,
        "ineligible_reason": ineligible_reason,
    }


# ──────────────────────────────────────────────────────────────
# Ranking formula — cross-sectional percentiles
# ──────────────────────────────────────────────────────────────

def rank_universe(symbol_metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Apply the 6-factor universe ranking formula to all eligible symbols.
    Returns list sorted by universe_rank_score descending.

    universe_rank_score = (
        0.25 * liquidity_pct
      + 0.15 * spread_pct_inv
      + 0.20 * volume_spike_pct
      + 0.15 * atr_pct
      + 0.15 * freshness_pct
      + 0.10 * cost_efficiency
    )
    """
    eligible = [m for m in symbol_metrics if m.get("eligible", False)]
    ineligible = [m for m in symbol_metrics if not m.get("eligible", False)]

    if not eligible:
        return ineligible

    # Cross-sectional value lists
    dollar_vols = [m["dollar_volume"] for m in eligible]
    spreads = [m["spread_bps"] for m in eligible]          # lower = better
    vol_spikes = [m["volume_spike_ratio"] for m in eligible]
    atrs = [m["atr_over_price"] for m in eligible]
    freshnesses = [m["freshness"] for m in eligible]
    cost_effs = [m["cost_efficiency"] for m in eligible]

    ranked = []
    for m in eligible:
        liq_pct = _percentile_rank(m["dollar_volume"], dollar_vols)
        # Spread: LOWER spread is better → invert percentile
        spread_pct_inv = 1.0 - _percentile_rank(m["spread_bps"], spreads)
        vol_pct = _percentile_rank(m["volume_spike_ratio"], vol_spikes)
        atr_pct = _percentile_rank(m["atr_over_price"], atrs)
        fresh_pct = m["freshness"]  # already 0–1, use directly
        cost_pct = m["cost_efficiency"]  # already 0–1

        rank_score = (
            0.25 * liq_pct
            + 0.15 * spread_pct_inv
            + 0.20 * vol_pct
            + 0.15 * atr_pct
            + 0.15 * fresh_pct
            + 0.10 * cost_pct
        )

        ranked.append(
            {
                **m,
                "universe_rank_score": round(rank_score, 4),
                "rank_components": {
                    "liquidity_pct": round(liq_pct, 4),
                    "spread_pct_inv": round(spread_pct_inv, 4),
                    "volume_spike_pct": round(vol_pct, 4),
                    "atr_pct": round(atr_pct, 4),
                    "freshness_pct": round(fresh_pct, 4),
                    "cost_efficiency": round(cost_pct, 4),
                },
                "ranked": True,
                "dropped": rank_score < MIN_RANK_SCORE,
            }
        )

    # Sort by rank descending
    ranked.sort(key=lambda x: x["universe_rank_score"], reverse=True)

    # Merge back ineligible (with rank 0)
    for m in ineligible:
        ranked.append(
            {
                **m,
                "universe_rank_score": 0.0,
                "ranked": False,
                "dropped": True,
            }
        )

    return ranked


# ──────────────────────────────────────────────────────────────
# Pipeline output snapshot
# ──────────────────────────────────────────────────────────────

def build_pipeline_snapshot(
    available: list[str],
    symbol_metrics: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
    *,
    max_shortlist: int = MAX_EXECUTION_SHORTLIST,
    cycle_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Returns the full funnel snapshot:
      Available → Cached → Eligible → Ranked → Execution Shortlist

    Each layer is an immutable snapshot with a cycle_id for traceability.
    """
    cycle_id = cycle_id or uuid.uuid4().hex[:12]

    cached = [m["symbol"] for m in symbol_metrics]
    eligible_syms = [r for r in ranked if r.get("eligible") and not r.get("dropped")]
    shortlist = [r for r in eligible_syms[:max_shortlist]]

    return {
        "cycle_id": cycle_id,
        "built_at": datetime.utcnow().isoformat() + "Z",
        "funnel": {
            "available": len(available),
            "cached": len(cached),
            "eligible": len(eligible_syms),
            "ranked": len(eligible_syms),
            "execution_shortlist": len(shortlist),
        },
        "available_symbols": available,
        "cached_symbols": cached,
        "eligible": eligible_syms,
        "shortlist": shortlist,
        "all_ranked": ranked,
        "min_rank_threshold": MIN_RANK_SCORE,
    }
