"""
Conservative cost model — edge_after_cost_bps drives all entry decisions.

Research formula:
  edge_after_cost_bps = expected_move_bps - (2*fee_bps + spread_bps + slippage_buffer_bps)
No trade unless edge_after_cost_bps >= min_edge_after_cost_bps
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.services.engine_config import cfg_get


@dataclass
class CostModelResult:
    passed: bool
    block_reason_code: Optional[str]
    human_reason: Optional[str]
    expected_move_bps: float
    round_trip_fee_bps: float
    spread_bps: float
    slippage_buffer_bps: float
    total_cost_bps: float
    edge_after_cost_bps: float
    min_edge_after_cost_bps: float
    evidence: dict[str, Any]


def _normalize_bps(value: Optional[float], *, as_pct: bool = False) -> float:
    if value is None:
        return 0.0
    v = float(value)
    if as_pct or (0 < v < 1):
        return v * 10000.0 if v < 1 else v * 100.0
    if v < 100:
        return v * 100.0  # pct like 3.0 → 300 bps
    return v


def evaluate_edge_after_cost_bps(
    config: dict,
    *,
    expected_move_bps: Optional[float] = None,
    expected_move_pct: Optional[float] = None,
    spread_pct: Optional[float] = None,
    spread_bps: Optional[float] = None,
    tier: str = "TIER_ALT",
) -> CostModelResult:
    fee_bps = float(cfg_get(config, "cost.taker_fee_pct", 0.25)) * 100.0  # 25 bps default
    round_trip_fee_bps = 2 * fee_bps

    if spread_bps is not None:
        spread = float(spread_bps)
    elif spread_pct is not None:
        spread = float(spread_pct) * 10000.0 if float(spread_pct) < 1 else float(spread_pct) * 100.0
    else:
        spread = 0.0

    slip_key = "slippage_buffer_meme_pct" if "MEME" in tier else (
        "slippage_buffer_major_pct" if "MAJOR" in tier else "slippage_buffer_alt_pct"
    )
    slippage_buffer_bps = float(cfg_get(config, f"cost.{slip_key}", 0.10)) * 100.0

    if expected_move_bps is not None:
        move_bps = float(expected_move_bps)
    elif expected_move_pct is not None:
        move_bps = _normalize_bps(expected_move_pct)
    else:
        move_bps = 0.0

    total_cost_bps = round_trip_fee_bps + spread + slippage_buffer_bps
    edge_after = move_bps - total_cost_bps
    min_edge = float(cfg_get(config, "push_pull.min_edge_after_cost_bps", 50.0))

    evidence = {
        "expected_move_bps": round(move_bps, 2),
        "round_trip_fee_bps": round_trip_fee_bps,
        "spread_bps": round(spread, 2),
        "slippage_buffer_bps": round(slippage_buffer_bps, 2),
        "total_cost_bps": round(total_cost_bps, 2),
        "edge_after_cost_bps": round(edge_after, 2),
        "min_edge_after_cost_bps": min_edge,
        "tier": tier,
    }

    if expected_move_bps is None and expected_move_pct is None:
        return CostModelResult(
            passed=False,
            block_reason_code="NEGATIVE_EDGE_AFTER_COST",
            human_reason="Expected move unavailable — cannot compute edge after cost",
            expected_move_bps=0,
            round_trip_fee_bps=round_trip_fee_bps,
            spread_bps=spread,
            slippage_buffer_bps=slippage_buffer_bps,
            total_cost_bps=total_cost_bps,
            edge_after_cost_bps=edge_after,
            min_edge_after_cost_bps=min_edge,
            evidence=evidence,
        )

    if edge_after < min_edge:
        return CostModelResult(
            passed=False,
            block_reason_code="NEGATIVE_EDGE_AFTER_COST",
            human_reason=(
                f"Edge after cost {edge_after:.1f} bps below minimum {min_edge:.1f} bps "
                f"(move {move_bps:.1f} − cost {total_cost_bps:.1f})"
            ),
            expected_move_bps=move_bps,
            round_trip_fee_bps=round_trip_fee_bps,
            spread_bps=spread,
            slippage_buffer_bps=slippage_buffer_bps,
            total_cost_bps=total_cost_bps,
            edge_after_cost_bps=edge_after,
            min_edge_after_cost_bps=min_edge,
            evidence=evidence,
        )

    return CostModelResult(
        passed=True,
        block_reason_code=None,
        human_reason=None,
        expected_move_bps=move_bps,
        round_trip_fee_bps=round_trip_fee_bps,
        spread_bps=spread,
        slippage_buffer_bps=slippage_buffer_bps,
        total_cost_bps=total_cost_bps,
        edge_after_cost_bps=edge_after,
        min_edge_after_cost_bps=min_edge,
        evidence=evidence,
    )
