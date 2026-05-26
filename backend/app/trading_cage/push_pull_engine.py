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

    mom = float(momentum_1h or 0)
    body = float(body_pct or 0)
    vol = float(volume_spike or 1.0)
    spread_bps = float(spread_pct or 0) * 10000.0 if spread_pct and spread_pct < 1 else float(spread_pct or 0) * 100.0

    gates["momentum_burst"] = mom >= push_min
    gates["candle_quality"] = body >= body_min
    gates["volume_spike"] = vol >= vol_min
    gates["vwap_confirmation"] = vwap_confirm or body >= body_min
    gates["ema_confirmation"] = ema_confirm or mom >= push_min
    gates["spread_ok"] = spread_bps <= max_spread_bps
    gates["quote_fresh"] = quote_age_seconds is None or quote_age_seconds <= max_quote_age
    gates["bar_fresh"] = bar_age_minutes is None or bar_age_minutes <= max_bar_age
    gates["atr_valid"] = atr_valid
    gates["not_overextended"] = overextension is None or overextension <= overext_max

    cost = evaluate_edge_after_cost_bps(
        config,
        expected_move_pct=expected_move_pct,
        spread_pct=spread_pct,
        tier=tier,
    )
    gates["edge_after_cost_positive"] = cost.passed
    if not cost.passed:
        reasons.append(cost.block_reason_code or "NEGATIVE_EDGE_AFTER_COST")

    for gate, ok in gates.items():
        if not ok and gate not in ("vwap_confirmation", "ema_confirmation"):
            code = gate.upper()
            if gate == "edge_after_cost_positive":
                code = "NEGATIVE_EDGE_AFTER_COST"
            if code not in reasons:
                reasons.append(code)

    push_score = min(1.0, (mom / push_min) * 0.35 + (body / max(body_min, 0.01)) * 0.25 + min(vol / vol_min, 2) * 0.2 + (0.2 if cost.passed else 0))
    pull_exit_score = max(0.0, 1.0 - (overextension or 0) / max(overext_max, 0.01))
    trade_quality = push_score * 0.5 + pull_exit_score * 0.2 + (1.0 if cost.passed else 0) * 0.3

    entry_allowed = all(gates.values()) and cost.passed
    no_trade = None if entry_allowed else (reasons[0] if reasons else "GATE_FAILED")

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
        },
    )
