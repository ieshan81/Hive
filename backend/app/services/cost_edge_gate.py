"""Cost-aware edge gate — expected move must exceed round-trip cost × multiplier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.services.engine_config import cfg_get, current_promotion_stage, edge_multiplier
from app.services.symbol_tier_service import SymbolTierService, TIER_MEME_SUPPORTED


@dataclass
class CostEdgeResult:
    passed: bool
    block_reason_code: Optional[str]
    human_reason: Optional[str]
    edge_over_cost: Optional[float]
    evidence: dict[str, Any]


def evaluate_cost_edge(
    config: dict,
    *,
    expected_move_pct: Optional[float],
    spread_pct: Optional[float],
    tier: str,
    symbol_tiers: SymbolTierService | None = None,
) -> CostEdgeResult:
    taker = float(cfg_get(config, "cost.taker_fee_pct", 0.25))
    slip_key = "slippage_buffer_meme_pct" if tier == TIER_MEME_SUPPORTED else (
        "slippage_buffer_major_pct" if tier.endswith("MAJOR") or "MAJOR" in tier else "slippage_buffer_alt_pct"
    )
    slippage = float(cfg_get(config, f"cost.{slip_key}", 0.10))
    spread = float(spread_pct or 0) * 100 if spread_pct is not None and spread_pct < 1 else float(spread_pct or 0)
    if spread_pct is not None and spread_pct < 1:
        spread = spread_pct * 100

    round_trip = (2 * taker) + spread + slippage
    mult = edge_multiplier(config)
    if tier == TIER_MEME_SUPPORTED:
        extra = float(cfg_get(config, "symbol_tiers.meme_extra_edge_multiplier", 1.25))
        mult *= extra

    min_move = float(cfg_get(config, "cost.min_expected_move_pct", 0.15))
    required_edge_pct = mult * round_trip
    stage = current_promotion_stage(config)

    evidence: dict[str, Any] = {
        "expected_move_pct": expected_move_pct,
        "spread_pct": spread_pct,
        "spread_pct_cost_component": spread,
        "taker_fee_pct": taker,
        "slippage_buffer_pct": slippage,
        "round_trip_cost_pct": round_trip,
        "required_edge_pct": required_edge_pct,
        "edge_multiplier": mult,
        "promotion_stage": stage,
        "tier": tier,
    }

    if expected_move_pct is None:
        evidence["missing"] = ["expected_move_pct"]
        return CostEdgeResult(
            passed=False,
            block_reason_code="EDGE_BELOW_COST",
            human_reason="Expected move unavailable — cannot verify edge over cost",
            edge_over_cost=None,
            evidence=evidence,
        )

    move = float(expected_move_pct)
    if move < 1 and move > 0:
        move *= 100
    evidence["expected_move_pct_normalized"] = move

    if round_trip <= 0:
        return CostEdgeResult(
            passed=False,
            block_reason_code="EDGE_BELOW_COST",
            human_reason="Invalid round-trip cost",
            edge_over_cost=None,
            evidence=evidence,
        )

    eoc = move / round_trip
    evidence["edge_over_cost"] = eoc

    if move < max(required_edge_pct, min_move):
        return CostEdgeResult(
            passed=False,
            block_reason_code="EDGE_BELOW_COST",
            human_reason=(
                f"Expected move {move:.3f}% below required {required_edge_pct:.3f}% "
                f"(round-trip cost {round_trip:.3f}%, multiplier {mult})"
            ),
            edge_over_cost=eoc,
            evidence=evidence,
        )

    return CostEdgeResult(passed=True, block_reason_code=None, human_reason=None, edge_over_cost=eoc, evidence=evidence)
