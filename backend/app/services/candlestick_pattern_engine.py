"""Deterministic candlestick pattern scoring for paper exploration.

The pattern engine is advisory to the scanner. It never submits orders and it
does not grant broker permission. It converts candle geometry into structured
scores used by push-pull ranking and the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Any, Optional


@dataclass
class PatternMatch:
    pattern: str
    direction: str
    confidence: float
    geometry_score: float
    context_score: float
    volume_score: float
    confirmation_score: float
    reversal_risk_score: float
    continuation_score: float
    pullback_quality_score: float
    entry_reference: Optional[float]
    stop_reference: Optional[float]
    target_reference: Optional[float]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "geometry_score": round(self.geometry_score, 4),
            "context_score": round(self.context_score, 4),
            "volume_score": round(self.volume_score, 4),
            "confirmation_score": round(self.confirmation_score, 4),
            "reversal_risk_score": round(self.reversal_risk_score, 4),
            "continuation_score": round(self.continuation_score, 4),
            "pullback_quality_score": round(self.pullback_quality_score, 4),
            "entry_reference": self.entry_reference,
            "stop_reference": self.stop_reference,
            "target_reference": self.target_reference,
            "reason": self.reason,
        }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = exp(-value)
        return 1.0 / (1.0 + z)
    z = exp(value)
    return z / (1.0 + z)


def _body(bar: dict[str, Any]) -> float:
    return abs(_f(bar.get("close")) - _f(bar.get("open")))


def _height(bar: dict[str, Any]) -> float:
    return max(_f(bar.get("high")) - _f(bar.get("low")), 1e-9)


def _green(bar: dict[str, Any]) -> bool:
    return _f(bar.get("close")) >= _f(bar.get("open"))


def _red(bar: dict[str, Any]) -> bool:
    return _f(bar.get("close")) < _f(bar.get("open"))


def _body_bounds(bar: dict[str, Any]) -> tuple[float, float]:
    a = _f(bar.get("open"))
    b = _f(bar.get("close"))
    return min(a, b), max(a, b)


def _contained(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    inner_low, inner_high = _body_bounds(inner)
    outer_low, outer_high = _body_bounds(outer)
    if inner_low >= outer_low and inner_high <= outer_high:
        return 1.0
    overlap = max(0.0, min(inner_high, outer_high) - max(inner_low, outer_low))
    return _clamp(overlap / max(inner_high - inner_low, 1e-9))


def _avg_volume(bars: list[dict[str, Any]], n: int = 20) -> float:
    vols = [_f(b.get("volume")) for b in bars[-n:] if _f(b.get("volume")) > 0]
    return sum(vols) / len(vols) if vols else 0.0


def _volume_score(bars: list[dict[str, Any]]) -> float:
    if not bars:
        return 0.5
    avg = _avg_volume(bars[:-1] or bars)
    cur = _f(bars[-1].get("volume"))
    if avg <= 0 or cur <= 0:
        return 0.5
    return _clamp(_sigmoid(((cur / avg) - 1.0) * 1.6))


def _ema(values: list[float], period: int = 20) -> Optional[float]:
    vals = [v for v in values if v > 0]
    if not vals:
        return None
    k = 2.0 / (period + 1)
    out = vals[0]
    for v in vals[1:]:
        out = v * k + out * (1.0 - k)
    return out


def _trend_context(bars: list[dict[str, Any]], direction: str) -> float:
    if len(bars) < 8:
        return 0.55
    closes = [_f(b.get("close")) for b in bars[-20:]]
    ema = _ema(closes, 20) or closes[-1]
    slope = closes[-1] - closes[max(0, len(closes) - 8)]
    if direction == "long":
        above = 1.0 if closes[-1] >= ema else 0.35
        slope_score = 1.0 if slope >= 0 else 0.35
    else:
        above = 1.0 if closes[-1] <= ema else 0.35
        slope_score = 1.0 if slope <= 0 else 0.35
    return _clamp(0.55 * above + 0.45 * slope_score)


def _confidence(geometry: float, context: float, volume: float, confirmation: float) -> float:
    return _clamp(0.35 * geometry + 0.25 * context + 0.20 * volume + 0.20 * confirmation)


def _mk(
    pattern: str,
    direction: str,
    bars: list[dict[str, Any]],
    geometry: float,
    confirmation: float,
    pullback: float,
    reversal: float,
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
    reason: str,
) -> PatternMatch:
    context = _trend_context(bars, direction)
    vol = _volume_score(bars)
    conf = _confidence(geometry, context, vol, confirmation)
    continuation = _clamp((1.0 - reversal) * pullback * context)
    return PatternMatch(
        pattern=pattern,
        direction=direction,
        confidence=conf,
        geometry_score=geometry,
        context_score=context,
        volume_score=vol,
        confirmation_score=confirmation,
        reversal_risk_score=_clamp(reversal),
        continuation_score=continuation,
        pullback_quality_score=_clamp(pullback),
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        reason=reason,
    )


def detect_candlestick_patterns(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[PatternMatch] = []
    if len(bars) < 3:
        return []
    b1, b2, b3 = bars[-3], bars[-2], bars[-1]
    last = bars[-1]
    prev = bars[-2]

    # Bullish Harami: large red mother, small green inside, confirmation up.
    if _red(b1) and _green(b2):
        mother_body = _body(b1)
        inside_body = _body(b2)
        containment = _contained(b2, b1)
        body_ratio = inside_body / max(mother_body, 1e-9)
        geometry = _clamp(containment * (1.0 - body_ratio))
        confirmation = 1.0 if _f(b3.get("close")) > max(_f(b2.get("high")), _f(b1.get("open"))) else 0.45
        if geometry >= 0.35:
            matches.append(
                _mk(
                    "bullish_harami",
                    "long",
                    bars,
                    geometry,
                    confirmation,
                    pullback=_clamp(1.0 - body_ratio),
                    reversal=0.25 if confirmation >= 0.75 else 0.45,
                    entry=max(_f(b2.get("high")), _f(b3.get("close"))),
                    stop=_f(b1.get("low")),
                    target=_f(b1.get("high")),
                    reason="Small bullish candle held inside a bearish mother candle during pullback.",
                )
            )

    # Bearish Harami: large green mother, small red inside, confirmation down.
    if _green(b1) and _red(b2):
        mother_body = _body(b1)
        inside_body = _body(b2)
        containment = _contained(b2, b1)
        body_ratio = inside_body / max(mother_body, 1e-9)
        geometry = _clamp(containment * (1.0 - body_ratio))
        confirmation = 1.0 if _f(b3.get("close")) < min(_f(b2.get("low")), _f(b1.get("open"))) else 0.45
        if geometry >= 0.35:
            matches.append(
                _mk(
                    "bearish_harami",
                    "short",
                    bars,
                    geometry,
                    confirmation,
                    pullback=_clamp(1.0 - body_ratio),
                    reversal=0.25 if confirmation >= 0.75 else 0.5,
                    entry=min(_f(b2.get("low")), _f(b3.get("close"))),
                    stop=_f(b1.get("high")),
                    target=_f(b1.get("low")),
                    reason="Small bearish candle held inside a bullish mother candle near possible exhaustion.",
                )
            )

    prev_low, prev_high = _body_bounds(prev)
    last_low, last_high = _body_bounds(last)
    engulf = last_low <= prev_low and last_high >= prev_high and _body(last) > _body(prev)
    if engulf:
        direction = "long" if _green(last) else "short"
        matches.append(
            _mk(
                "engulfing",
                direction,
                bars,
                geometry=_clamp(_body(last) / max(_body(prev), 1e-9) / 2.0),
                confirmation=0.8,
                pullback=0.65,
                reversal=0.25,
                entry=_f(last.get("close")),
                stop=_f(last.get("low") if direction == "long" else last.get("high")),
                target=None,
                reason="Current body engulfed prior body with directional follow-through.",
            )
        )

    upper_wick = _f(last.get("high")) - max(_f(last.get("open")), _f(last.get("close")))
    lower_wick = min(_f(last.get("open")), _f(last.get("close"))) - _f(last.get("low"))
    height = _height(last)
    if max(upper_wick, lower_wick) / height >= 0.66:
        direction = "long" if lower_wick > upper_wick else "short"
        matches.append(
            _mk(
                "pin_bar",
                direction,
                bars,
                geometry=_clamp(max(upper_wick, lower_wick) / height),
                confirmation=0.65,
                pullback=0.7,
                reversal=0.28,
                entry=_f(last.get("close")),
                stop=_f(last.get("low") if direction == "long" else last.get("high")),
                target=None,
                reason="Long rejection wick marks a liquidity sweep or failed move.",
            )
        )

    if _f(last.get("high")) <= _f(prev.get("high")) and _f(last.get("low")) >= _f(prev.get("low")):
        matches.append(
            _mk(
                "inside_bar",
                "long" if _green(last) else "short",
                bars,
                geometry=0.72,
                confirmation=0.45,
                pullback=0.55,
                reversal=0.4,
                entry=_f(prev.get("high") if _green(last) else prev.get("low")),
                stop=_f(prev.get("low") if _green(last) else prev.get("high")),
                target=None,
                reason="Inside bar compression; wait for breakout confirmation.",
            )
        )

    avg_body = sum(_body(b) for b in bars[-12:-1]) / max(len(bars[-12:-1]), 1)
    if avg_body > 0 and _body(last) >= avg_body * 1.8 and _body(last) / height >= 0.6:
        matches.append(
            _mk(
                "momentum_candle",
                "long" if _green(last) else "short",
                bars,
                geometry=_clamp(_body(last) / max(avg_body * 2.5, 1e-9)),
                confirmation=0.7,
                pullback=0.4,
                reversal=0.35,
                entry=_f(last.get("close")),
                stop=_f(last.get("low") if _green(last) else last.get("high")),
                target=None,
                reason="Large body and elevated range indicate impulse; prefer pullback entry.",
            )
        )

    if max(upper_wick, lower_wick) / height >= 0.5 and _volume_score(bars) >= 0.75:
        matches.append(
            _mk(
                "exhaustion_candle",
                "short" if upper_wick > lower_wick else "long",
                bars,
                geometry=_clamp(max(upper_wick, lower_wick) / height),
                confirmation=0.55,
                pullback=0.35,
                reversal=0.75,
                entry=_f(last.get("close")),
                stop=_f(last.get("high") if upper_wick > lower_wick else last.get("low")),
                target=None,
                reason="High-volume wick after expansion raises exhaustion/reversal risk.",
            )
        )

    if len(bars) >= 6:
        prior_high = max(_f(b.get("high")) for b in bars[-6:-1])
        prior_low = min(_f(b.get("low")) for b in bars[-6:-1])
        if _f(last.get("high")) > prior_high and _f(last.get("close")) < prior_high:
            matches.append(
                _mk(
                    "failed_breakout",
                    "short",
                    bars,
                    geometry=0.8,
                    confirmation=0.7,
                    pullback=0.6,
                    reversal=0.65,
                    entry=_f(last.get("close")),
                    stop=_f(last.get("high")),
                    target=prior_low,
                    reason="Break above range failed and closed back inside.",
                )
            )
        if _f(last.get("low")) < prior_low and _f(last.get("close")) > prior_low:
            matches.append(
                _mk(
                    "failed_breakout",
                    "long",
                    bars,
                    geometry=0.8,
                    confirmation=0.7,
                    pullback=0.6,
                    reversal=0.65,
                    entry=_f(last.get("close")),
                    stop=_f(last.get("low")),
                    target=prior_high,
                    reason="Break below range failed and closed back inside.",
                )
            )

    out = [m.to_dict() for m in matches]
    out.sort(key=lambda row: float(row.get("confidence") or 0), reverse=True)
    return out


def top_pattern(bars: list[dict[str, Any]]) -> dict[str, Any]:
    matches = detect_candlestick_patterns(bars)
    if matches:
        return matches[0]
    return {
        "pattern": "none",
        "direction": "long",
        "confidence": 0.0,
        "geometry_score": 0.0,
        "context_score": 0.5,
        "volume_score": 0.5,
        "confirmation_score": 0.0,
        "reversal_risk_score": 0.35,
        "continuation_score": 0.45,
        "pullback_quality_score": 0.45,
        "reason": "No confirmed candle pattern in the latest window.",
    }
