"""
Push-Pull strategy scoring — configurable state machine inputs.

Scan → Detect push → Score → Validate → Submit → Watch → Exit → Learn
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.engine_config import cfg_get
from app.trading_cage.cost_model import evaluate_edge_after_cost_bps


@dataclass
class PushPullScore:
    push_score: float
    pull_exit_score: float
    trade_quality_score: float
    edge_after_cost_bps: float
    entry_allowed: bool
    no_trade_reason: Optional[str]
    gate_results: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


def _threshold(config: dict, key: str, default: float) -> float:
    pp = config.get("push_pull") or {}
    return float(pp.get(key, cfg_get(config, f"push_pull.{key}", default)))


def _paper_exploration_on(config: dict) -> bool:
    exp = config.get("exploration") or {}
    promotion = (config.get("promotion") or {}).get("current_stage", "PAPER")
    execution = config.get("execution") or {}
    live_orders = bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))
    return promotion == "PAPER" and bool(exp.get("enabled", True)) and not live_orders


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_push_pull_setup(
    config: dict,
    *,
    symbol: str,
    momentum_1h: Optional[float] = None,
    body_pct: Optional[float] = None,
    volume_spike: Optional[float] = None,
    spread_pct: Optional[float] = None,
    quote_age_seconds: Optional[float] = None,
    bar_age_minutes: Optional[float] = None,
    vwap_confirm: bool = False,
    ema_confirm: bool = False,
    atr_valid: bool = True,
    overextension: Optional[float] = None,
    expected_move_pct: Optional[float] = None,
    tier: str = "TIER_ALT",
    pattern_confidence: Optional[float] = None,
    pullback_quality_score: Optional[float] = None,
    reversal_risk_score: Optional[float] = None,
    continuation_score: Optional[float] = None,
) -> PushPullScore:
    """Score a push setup; returns entry_allowed and no_trade_reason."""
    gates: dict[str, bool] = {}
    reasons: list[str] = []

    push_min = _threshold(config, "push_strength_min", 0.004)
    body_min = _threshold(config, "body_pct_min", 0.35)
    vol_min = _threshold(config, "volume_spike_min", 1.5)
    max_spread_bps = _threshold(config, "max_spread_bps", 50.0)
    max_quote_age = _threshold(config, "max_quote_age_seconds", 30.0)
    max_bar_age = _threshold(config, "max_bar_age_minutes", 120.0)
    overext_max = _threshold(config, "overextension_max", 3.0)
    base_enter = _threshold(config, "enter_threshold", 0.70)
    min_quality = _threshold(config, "min_trade_quality", 0.60)
    paper_floor = _threshold(config, "paper_exploration_enter_floor", 0.42)
    paper_min_quality = _threshold(config, "paper_exploration_min_quality", 0.38)

    mom = float(momentum_1h or 0)
    body = float(body_pct or 0)
    vol = float(volume_spike or 1.0)
    spread_bps = float(spread_pct or 0) * 10000.0 if spread_pct and spread_pct < 1 else float(spread_pct or 0) * 100.0
    pattern_score = _clamp(float(pattern_confidence or 0.0), 0.0, 1.0)
    pullback_score = _clamp(float(pullback_quality_score if pullback_quality_score is not None else 0.55), 0.0, 1.0)
    reversal_risk = _clamp(float(reversal_risk_score if reversal_risk_score is not None else 0.35), 0.0, 1.0)
    continuation = _clamp(float(continuation_score if continuation_score is not None else 0.55), 0.0, 1.0)

    cost = evaluate_edge_after_cost_bps(
        config,
        expected_move_pct=expected_move_pct,
        spread_pct=spread_pct,
        tier=tier,
    )

    momentum_component = _clamp(max(0.0, mom) / max(push_min, 0.0001), 0.0, 2.0)
    body_component = _clamp(body / max(body_min, 0.01), 0.0, 2.0)
    volume_component = _clamp(vol / max(vol_min, 0.01), 0.0, 2.0)
    freshness_component = 1.0
    if quote_age_seconds is not None:
        freshness_component *= _clamp(1.0 - (quote_age_seconds / max(max_quote_age * 2, 1.0)), 0.0, 1.0)
    if bar_age_minutes is not None:
        freshness_component *= _clamp(1.0 - (bar_age_minutes / max(max_bar_age * 2, 1.0)), 0.0, 1.0)
    edge_component = _clamp(cost.edge_after_cost_bps / max(_threshold(config, "min_edge_after_cost_bps", 25.0), 1.0), 0.0, 2.0)

    push_score_raw = (
        0.25 * body_component
        + 0.25 * volume_component
        + 0.20 * momentum_component
        + 0.15 * edge_component
        + 0.10 * (1.0 if (vwap_confirm or body >= body_min) else 0.0)
        + 0.05 * freshness_component
    )
    push_score = _clamp(push_score_raw / 1.35, 0.0, 1.0)

    exploration_on = _paper_exploration_on(config)
    adaptive_enter = base_enter
    adaptive_enter -= min(0.16, max(0.0, cost.edge_after_cost_bps) / 2500.0)
    adaptive_enter -= min(0.10, max(0.0, vol - vol_min) / max(vol_min * 8, 1.0))
    adaptive_enter += min(0.12, max(0.0, spread_bps - (max_spread_bps * 0.5)) / max(max_spread_bps * 4, 1.0))
    if exploration_on:
        adaptive_enter = max(paper_floor, adaptive_enter - 0.08)
        min_quality = min(min_quality, paper_min_quality)
    adaptive_enter = _clamp(adaptive_enter, paper_floor if exploration_on else 0.55, 0.92)

    gates["push_above_threshold"] = push_score >= adaptive_enter
    gates["candle_quality"] = body >= body_min
    gates["volume_spike"] = vol >= vol_min
    gates["vwap_confirmation"] = vwap_confirm or body >= body_min
    gates["ema_confirmation"] = ema_confirm or mom >= push_min or (exploration_on and push_score >= adaptive_enter and body >= body_min)
    gates["spread_ok"] = spread_bps <= max_spread_bps
    gates["quote_fresh"] = quote_age_seconds is None or quote_age_seconds <= max_quote_age
    gates["bar_fresh"] = bar_age_minutes is None or bar_age_minutes <= max_bar_age
    gates["atr_valid"] = atr_valid
    gates["not_overextended"] = overextension is None or overextension <= overext_max
    gates["edge_after_cost_positive"] = cost.passed
    if not cost.passed:
        reasons.append(cost.block_reason_code or "NEGATIVE_EDGE_AFTER_COST")

    for gate, ok in gates.items():
        if not ok:
            code = gate.upper()
            if gate == "push_above_threshold":
                code = "PUSH_BELOW_THRESHOLD"
            if gate == "edge_after_cost_positive":
                code = "NEGATIVE_EDGE_AFTER_COST"
            if gate == "spread_ok":
                code = "SPREAD_TOO_WIDE"
            if gate == "quote_fresh":
                code = "STALE_QUOTE"
            if gate == "bar_fresh":
                code = "STALE_BAR"
            if gate == "atr_valid":
                code = "ATR_INVALID"
            if code not in reasons:
                reasons.append(code)

    pull_exit_score = max(0.0, 1.0 - (overextension or 0) / max(overext_max, 0.01))
    research_quality = (
        push_score * 0.25
        + pullback_score * 0.30
        + continuation * 0.25
        + pattern_score * 0.20
    ) * (1.0 - reversal_risk * 0.5)
    legacy_quality = push_score * 0.5 + pull_exit_score * 0.2 + (1.0 if cost.passed else 0) * 0.3
    trade_quality = max(research_quality, legacy_quality if pattern_score <= 0 else (research_quality * 0.75 + legacy_quality * 0.25))
    gates["quality_above_min"] = trade_quality >= min_quality
    if not gates["quality_above_min"] and "QUALITY_BELOW_MIN" not in reasons:
        reasons.append("QUALITY_BELOW_MIN")

    hard_gate_names = {
        "spread_ok",
        "quote_fresh",
        "bar_fresh",
        "atr_valid",
        "edge_after_cost_positive",
        "quality_above_min",
    }
    if not exploration_on:
        hard_gate_names.update(
            {
                "push_above_threshold",
                "candle_quality",
                "volume_spike",
                "vwap_confirmation",
                "ema_confirmation",
                "not_overextended",
            }
        )
    hard_gates = {k: v for k, v in gates.items() if k in hard_gate_names}
    soft_gates = {k: v for k, v in gates.items() if k not in hard_gate_names}
    entry_allowed = all(hard_gates.values()) and cost.passed
    hard_reasons = [
        r
        for r in reasons
        if (
            r.lower() in hard_gate_names
            or r in ("NEGATIVE_EDGE_AFTER_COST", "SPREAD_TOO_WIDE", "STALE_QUOTE", "STALE_BAR", "ATR_INVALID", "QUALITY_BELOW_MIN")
        )
    ]
    no_trade = None if entry_allowed else (hard_reasons[0] if hard_reasons else (reasons[0] if reasons else "GATE_FAILED"))

    return PushPullScore(
        push_score=round(push_score, 4),
        pull_exit_score=round(pull_exit_score, 4),
        trade_quality_score=round(trade_quality, 4),
        edge_after_cost_bps=cost.edge_after_cost_bps,
        entry_allowed=entry_allowed,
        no_trade_reason=no_trade,
        gate_results=gates,
        evidence={
            "symbol": symbol,
            "cost": cost.evidence,
            "momentum_1h": mom,
            "body_pct": body,
            "volume_spike": vol,
            "spread_bps": spread_bps,
            "adaptive_enter_threshold": round(adaptive_enter, 4),
            "min_trade_quality": round(min_quality, 4),
            "paper_exploration": exploration_on,
            "hard_gate_results": hard_gates,
            "soft_gate_results": soft_gates,
            "soft_concerns": [k for k, ok in soft_gates.items() if not ok],
            "pattern_confidence": round(pattern_score, 4),
            "pullback_quality_score": round(pullback_score, 4),
            "reversal_risk_score": round(reversal_risk, 4),
            "continuation_score": round(continuation, 4),
            "research_trade_quality": round(research_quality, 4),
            "push_score_0_100": round(push_score * 100, 2),
            "trade_quality_0_100": round(trade_quality * 100, 2),
        },
    )
