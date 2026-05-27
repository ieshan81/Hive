"""
Push-Pull Candle Strategy — Score Engine.

Implements the exact formulas from the Caged Hive Quant research spec:
  push_score       (0–100): body quality, vol spike, VWAP confirm, ATR momentum, freshness
  edge_after_cost_bps     : expected move minus round-trip taker + spread + slippage
  trade_quality_score     : composite entry gate (push + edge + rank + sentiment + regime)
  pull_exit_score  (0–100): profit progress, trailing drop, ATR stop proximity, mom reversal

All formulas are deterministic — no broker calls here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional


# ──────────────────────────────────────────────────────────────
# 1. Sigmoid helper
# ──────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    """Numerically-stable logistic sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


# ──────────────────────────────────────────────────────────────
# 2. Volatility Regime Detection
# ──────────────────────────────────────────────────────────────

REGIMES = ("quiet", "normal", "vol", "panic")

# Regime thresholds (realized_vol_20m / realized_vol_1d)
_REGIME_BOUNDS = (
    (0.5, "quiet"),
    (1.2, "normal"),
    (2.0, "vol"),
)


def classify_regime(bars_1m: list[dict]) -> str:
    """
    regime = classify(realized_vol_20m / realized_vol_1d)
    quiet (<0.5), normal (0.5–1.2), vol (1.2–2.0), panic (>2.0)
    Requires at least 480 bars (1 trading day + 20m) for meaningful result.
    Falls back to 'normal' with sparse data.
    """
    if len(bars_1m) < 30:
        return "normal"

    def _log_returns(bars: list[dict]) -> list[float]:
        out = []
        for i in range(1, len(bars)):
            p0 = bars[i - 1]["close"]
            p1 = bars[i]["close"]
            if p0 > 0:
                out.append(math.log(p1 / p0))
        return out

    recent_20 = bars_1m[-20:]
    recent_480 = bars_1m[-480:] if len(bars_1m) >= 480 else bars_1m

    rets_20 = _log_returns(recent_20)
    rets_1d = _log_returns(recent_480)
    if not rets_20 or not rets_1d:
        return "normal"

    def _std(lst: list[float]) -> float:
        n = len(lst)
        if n < 2:
            return 0.0
        m = sum(lst) / n
        return math.sqrt(sum((x - m) ** 2 for x in lst) / (n - 1))

    vol_20m = _std(rets_20)
    vol_1d = _std(rets_1d)
    if vol_1d == 0:
        return "normal"

    ratio = vol_20m / vol_1d
    for threshold, label in _REGIME_BOUNDS:
        if ratio < threshold:
            return label
    return "panic"


def regime_enter_threshold(regime: str) -> float:
    """push_enter threshold per regime (normal=70, quiet=75, vol=65, panic=85)."""
    return {"quiet": 75.0, "normal": 70.0, "vol": 65.0, "panic": 85.0}.get(regime, 70.0)


def regime_fit_score(regime: str) -> float:
    """0–1 score indicating how well regime supports new entries."""
    return {"quiet": 0.9, "normal": 1.0, "vol": 0.7, "panic": 0.2}.get(regime, 0.8)


# ──────────────────────────────────────────────────────────────
# 3. ATR (Wilder 1978)
# ──────────────────────────────────────────────────────────────

def compute_atr(bars: list[dict], period: int = 14) -> float:
    """
    ATR_t = (ATR_{t-1} * 13 + TR_t) / 14
    TR_t = max(H-L, |H-prev_close|, |L-prev_close|)
    Returns the latest ATR value (0 if insufficient bars).
    """
    if len(bars) < 2:
        return 0.0

    trs = []
    for i in range(1, len(bars)):
        h = bars[i]["high"]
        l = bars[i]["low"]
        pc = bars[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)

    if not trs:
        return 0.0

    # Seed with simple average of first `period` TRs
    atr = sum(trs[: period]) / min(period, len(trs))
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ──────────────────────────────────────────────────────────────
# 4. VWAP (running from bar[0])
# ──────────────────────────────────────────────────────────────

def compute_vwap(bars: list[dict]) -> Optional[float]:
    """Running VWAP over supplied bars."""
    total_pv = 0.0
    total_v = 0.0
    for b in bars:
        typ_price = (b["high"] + b["low"] + b["close"]) / 3.0
        v = b.get("volume", 0.0)
        total_pv += typ_price * v
        total_v += v
    return total_pv / total_v if total_v > 0 else None


# ──────────────────────────────────────────────────────────────
# 5. push_score (0–100)
# ──────────────────────────────────────────────────────────────

def compute_push_score(
    bars_1m: list[dict],
    quote: dict,
    *,
    bar_age_seconds: float = 0.0,
    side: str = "buy",
) -> float:
    """
    push_score = 100 * (
        0.25 * body_quality
      + 0.25 * vol_spike
      + 0.20 * vwap_confirm
      + 0.20 * atr_momentum
      + 0.10 * freshness
    )

    body_quality  = sigmoid(((|close-open|/(high-low+ε)) - 0.55) * 8)
    vol_spike     = sigmoid((vol/sma20(vol) - 1.5) * 2.5)
    vwap_confirm  = sigmoid((close - vwap) / atr * 3) for long; mirror for short
    atr_momentum  = sigmoid((ret_3bar / atr - 0.35) * 4)
    freshness     = clamp(1 - bar_age_s / 60, 0, 1)
    """
    if len(bars_1m) < 5:
        return 0.0

    latest = bars_1m[-1]
    o, h, l, c = latest["open"], latest["high"], latest["low"], latest["close"]
    vol = latest.get("volume", 0.0)

    # body_quality
    body = abs(c - o)
    candle_range = h - l + 1e-10
    body_quality = _sigmoid(((body / candle_range) - 0.55) * 8)

    # vol_spike — SMA20 of volume
    vols = [b.get("volume", 0.0) for b in bars_1m[-21:-1]]
    sma20 = sum(vols) / max(len(vols), 1)
    vol_spike = _sigmoid(((vol / (sma20 + 1e-10)) - 1.5) * 2.5) if sma20 > 0 else 0.5

    # ATR and VWAP
    atr = compute_atr(bars_1m[-15:], period=14) if len(bars_1m) >= 15 else (h - l + 1e-10)
    if atr == 0:
        atr = 1e-6
    vwap = compute_vwap(bars_1m[-20:])
    if vwap is None:
        vwap = c

    # vwap_confirm
    direction = 1.0 if side == "buy" else -1.0
    vwap_confirm = _sigmoid(direction * (c - vwap) / atr * 3)

    # atr_momentum — 3-bar return normalised by ATR
    if len(bars_1m) >= 4:
        ret_3bar = bars_1m[-1]["close"] - bars_1m[-4]["close"]
    else:
        ret_3bar = 0.0
    atr_momentum = _sigmoid(direction * (ret_3bar / atr - 0.35) * 4)

    # freshness
    freshness = _clamp(1.0 - bar_age_seconds / 60.0)

    score = 100.0 * (
        0.25 * body_quality
        + 0.25 * vol_spike
        + 0.20 * vwap_confirm
        + 0.20 * atr_momentum
        + 0.10 * freshness
    )
    return _clamp(score, 0.0, 100.0)


# ──────────────────────────────────────────────────────────────
# 6. edge_after_cost_bps
# ──────────────────────────────────────────────────────────────

# Fee defaults per spec (Alpaca Crypto Fee Schedule — Tier 1)
DEFAULT_TAKER_FEE_BPS = 25  # 0.25%
DEFAULT_MAKER_FEE_BPS = 15
DEFAULT_SLIPPAGE_BUFFER_BPS = 8  # conservative estimate


def compute_edge_after_cost_bps(
    bars_1m: list[dict],
    quote: dict,
    *,
    taker_fee_bps: float = DEFAULT_TAKER_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BUFFER_BPS,
    atr_continuation_factor: float = 0.5,
) -> float:
    """
    expected_move_bps  = predicted_continuation_atr * 10000 / price
    roundtrip_cost_bps = (taker_fee_in + taker_fee_out) + spread_bps + slippage_buffer_bps
    edge_after_cost    = expected_move_bps - roundtrip_cost_bps

    predicted_continuation = atr_continuation_factor * ATR(14)
    """
    if len(bars_1m) < 3:
        return -999.0

    price = quote.get("mid") or bars_1m[-1]["close"]
    if price <= 0:
        return -999.0

    atr = compute_atr(bars_1m[-15:], period=14) if len(bars_1m) >= 15 else (bars_1m[-1]["high"] - bars_1m[-1]["low"])
    predicted_continuation = atr_continuation_factor * atr
    expected_move_bps = predicted_continuation * 10_000 / price

    bid = quote.get("bid", price * 0.999)
    ask = quote.get("ask", price * 1.001)
    spread_bps = ((ask - bid) / price) * 10_000 if price > 0 else 10.0

    roundtrip_cost_bps = (taker_fee_bps * 2) + spread_bps + slippage_bps
    return expected_move_bps - roundtrip_cost_bps


# ──────────────────────────────────────────────────────────────
# 7. trade_quality_score (composite entry gate)
# ──────────────────────────────────────────────────────────────

def compute_trade_quality_score(
    push_score: float,
    edge_after_cost_bps: float,
    universe_rank_score: float = 0.5,
    sentiment_alignment: float = 0.0,
    regime: str = "normal",
    *,
    min_edge_bps: float = 25.0,
) -> float:
    """
    trade_quality = 0.40 * push_score
                  + 0.30 * min(edge_after_cost_bps / 50, 1) * 100
                  + 0.15 * universe_rank_score * 100
                  + 0.10 * sentiment_alignment * 100
                  + 0.05 * regime_fit * 100

    sentiment_alignment is clamped to [-0.10, +0.10] per spec (max ±10% influence).
    """
    edge_component = _clamp(edge_after_cost_bps / 50.0) * 100.0
    sentiment_clamped = _clamp(sentiment_alignment, -0.10, 0.10) * 100.0 / 0.10  # scale to 0–100 range around 50
    regime_fit = regime_fit_score(regime)

    score = (
        0.40 * _clamp(push_score, 0.0, 100.0)
        + 0.30 * edge_component
        + 0.15 * _clamp(universe_rank_score, 0.0, 1.0) * 100.0
        + 0.10 * (50.0 + sentiment_clamped)  # 50 = neutral baseline
        + 0.05 * regime_fit * 100.0
    )
    return _clamp(score, 0.0, 100.0)


# ──────────────────────────────────────────────────────────────
# 8. pull_exit_score (0–100)
# ──────────────────────────────────────────────────────────────

def compute_pull_exit_score(
    *,
    entry_price: float,
    current_price: float,
    peak_price: float,
    target_R: float,
    atr_stop_R: float,
    bars_held: int,
    max_bars: int = 30,
    quote_age_s: float = 0.0,
    quote_max_age_s: float = 10.0,
    spread_now: float = 0.0,
    spread_at_entry: float = 0.0,
    bars_1m: Optional[list[dict]] = None,
    side: str = "buy",
) -> float:
    """
    pull_exit_score = 100 * max(
        0.40 * profit_progress
      + 0.25 * trailing_drop
      + 0.20 * atr_stop_proximity
      + 0.15 * mom_reversal,
        stale_quote_flag,
        spread_expand_flag,
        timeout_flag
    )

    exit_threshold = 70.  Hard safety stop at 2.5 × ATR triggers regardless of score.
    """
    direction = 1.0 if side == "buy" else -1.0

    # unrealized_R — return in ATR units
    if atr_stop_R <= 0:
        atr_stop_R = abs(entry_price * 0.02) or 1.0

    unrealized_R = direction * (current_price - entry_price) / atr_stop_R
    peak_R = direction * (peak_price - entry_price) / atr_stop_R
    current_R = unrealized_R

    profit_progress = _clamp(unrealized_R / max(target_R, 1e-6))
    trailing_drop = _clamp(peak_R - current_R)
    atr_stop_proximity = _clamp(1.0 - (current_R + atr_stop_R) / atr_stop_R)

    stale_quote_flag = 1.0 if quote_age_s > quote_max_age_s else 0.0
    spread_expand_flag = 1.0 if (spread_at_entry > 0 and spread_now > 2.0 * spread_at_entry) else 0.0
    timeout_flag = 1.0 if bars_held >= max_bars else 0.0

    # mom_reversal — 2-bar momentum (reversal signal against position direction)
    if bars_1m and len(bars_1m) >= 3:
        bars = bars_1m
        ret_2bar = bars[-1]["close"] - bars[-3]["close"]
        atr_val = compute_atr(bars[-15:], period=14) if len(bars) >= 15 else (bars[-1]["high"] - bars[-1]["low"] + 1e-6)
        # Negative if momentum reversal (opposite to position direction)
        mom_reversal = _sigmoid(direction * (-ret_2bar / max(atr_val, 1e-6) - 0.2) * 5)
    else:
        mom_reversal = 0.0

    continuous_score = (
        0.40 * profit_progress
        + 0.25 * trailing_drop
        + 0.20 * atr_stop_proximity
        + 0.15 * mom_reversal
    )
    raw = max(continuous_score, stale_quote_flag, spread_expand_flag, timeout_flag)
    return _clamp(raw * 100.0, 0.0, 100.0)


# ──────────────────────────────────────────────────────────────
# 9. 5m bar confirmation
# ──────────────────────────────────────────────────────────────

def confirms_on_5m(bars_5m: list[dict], side: str = "buy") -> bool:
    """
    5m context confirmation: last 5m bar should lean in the same direction.
    True if the close is above the open (for buys) or below (for sells).
    """
    if not bars_5m:
        return True  # no data = don't block
    latest = bars_5m[-1]
    o, c = latest["open"], latest["close"]
    if side == "buy":
        return c >= o
    return c <= o


# ──────────────────────────────────────────────────────────────
# 10. no_trade_reason enum (all values from spec)
# ──────────────────────────────────────────────────────────────

NO_TRADE_REASONS = (
    "STALE_BAR",
    "STALE_QUOTE",
    "SPREAD_TOO_WIDE",
    "EDGE_NEGATIVE",
    "PUSH_BELOW_THRESHOLD",
    "QUALITY_BELOW_MIN",
    "MIN_NOTIONAL_NOT_MET",
    "BUYING_POWER_INSUFFICIENT",
    "OPEN_POSITION_EXISTS",
    "COOLDOWN_ACTIVE",
    "DUP_CLIENT_ORDER_ID",
    "KILL_SWITCH",
    "LIVE_LOCK",
    "PDT_BLOCK",
    "ALLOCATOR_REJECT",
    "OVEREXTENDED_VS_VWAP",
    "REGIME_PANIC_HALT",
    "PUMP_DUMP_FLAG",
    "REJECT_BY_AI_VETO",
)


# ──────────────────────────────────────────────────────────────
# 11. Full entry evaluation result (for scan service)
# ──────────────────────────────────────────────────────────────

def evaluate_entry(
    symbol: str,
    bars_1m: list[dict],
    bars_5m: list[dict],
    quote: dict,
    *,
    bar_age_seconds: float = 0.0,
    universe_rank_score: float = 0.5,
    sentiment_alignment: float = 0.0,
    taker_fee_bps: float = DEFAULT_TAKER_FEE_BPS,
    min_push_enter: float = 70.0,
    min_quality: float = 60.0,
    min_edge_bps: float = 25.0,
    regime: str = "normal",
    side: str = "buy",
) -> dict:
    """
    Full entry evaluation returning all scores, reasons, and pass/fail.
    Does NOT touch broker — purely deterministic signal computation.
    """
    reasons: list[str] = []

    if len(bars_1m) < 5:
        return {
            "symbol": symbol,
            "pass": False,
            "reason": "STALE_BAR",
            "push_score": 0.0,
            "edge_bps": -999.0,
            "quality_score": 0.0,
            "regime": regime,
        }

    push = compute_push_score(bars_1m, quote, bar_age_seconds=bar_age_seconds, side=side)
    edge = compute_edge_after_cost_bps(bars_1m, quote, taker_fee_bps=taker_fee_bps)
    quality = compute_trade_quality_score(push, edge, universe_rank_score, sentiment_alignment, regime)

    # Regime-adjusted push threshold
    adjusted_push_threshold = regime_enter_threshold(regime)

    # Stale data checks
    quote_age = quote.get("quote_age_seconds", 0.0)
    if quote_age > 10.0:
        reasons.append("STALE_QUOTE")
    if bar_age_seconds > 120.0:
        reasons.append("STALE_BAR")

    # Score gates
    if push < adjusted_push_threshold:
        reasons.append("PUSH_BELOW_THRESHOLD")
    if edge < min_edge_bps:
        reasons.append("EDGE_NEGATIVE")
    if quality < min_quality:
        reasons.append("QUALITY_BELOW_MIN")

    # 5m confirmation (advisory, not a hard block in this function)
    five_m_confirms = confirms_on_5m(bars_5m, side=side)

    passed = len(reasons) == 0

    return {
        "symbol": symbol,
        "pass": passed,
        "reason": reasons[0] if reasons else "ok",
        "reasons": reasons,
        "push_score": round(push, 2),
        "edge_bps": round(edge, 2),
        "quality_score": round(quality, 2),
        "universe_rank_score": round(universe_rank_score, 4),
        "sentiment_alignment": round(sentiment_alignment, 4),
        "regime": regime,
        "five_m_confirms": five_m_confirms,
        "bar_age_s": bar_age_seconds,
        "quote_age_s": quote_age,
        "atr14": round(compute_atr(bars_1m[-15:], 14) if len(bars_1m) >= 15 else 0.0, 6),
    }
