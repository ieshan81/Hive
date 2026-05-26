"""Reset-epoch-aware AI memory types — append-only, validated influence."""

from __future__ import annotations

from typing import Any, Optional

MEMORY_TYPES = frozenset(
    {
        "backtest_failure_pattern",
        "spread_kills_edge_pattern",
        "rejected_strategy_memory",
        "do_not_promote_recommendation",
        "sample_size_warning",
        "walk_forward_success",
        "paper_trade_success",
        "paper_trade_failure",
        "broker_behavior_memory",
        "risk_memory",
        "pump_dump_alert",
        "regime_change",
    }
)

RANKING_INFLUENCE_TYPES = frozenset(
    {
        "walk_forward_success",
        "paper_trade_success",
        "paper_trade_failure",
        "broker_behavior_memory",
        "backtest_failure_pattern",
        "spread_kills_edge_pattern",
    }
)


def memory_record(
    *,
    memory_type: str,
    lesson: str,
    reset_epoch_id: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
    evidence: Optional[dict] = None,
    confidence_impact: float = 0.0,
    future_behavior_change: Optional[str] = None,
    visible_to_ai: bool = True,
    can_influence_ranking: bool = False,
) -> dict[str, Any]:
    if memory_type not in MEMORY_TYPES:
        memory_type = "risk_memory"
    if can_influence_ranking and memory_type not in RANKING_INFLUENCE_TYPES:
        can_influence_ranking = False
    return {
        "type": memory_type,
        "lesson": lesson,
        "reset_epoch_id": reset_epoch_id,
        "symbol": symbol,
        "strategy": strategy,
        "evidence": evidence or {},
        "confidence_impact": confidence_impact,
        "future_behavior_change": future_behavior_change,
        "status": "active",
        "visible_to_ai": visible_to_ai,
        "can_influence_ranking": can_influence_ranking,
    }
