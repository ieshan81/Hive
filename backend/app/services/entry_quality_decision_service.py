"""Single paper-entry quality decision: edge first, not a block maze."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.engine_config import cfg_get


def _num(v: Any, fallback: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else fallback
    except (TypeError, ValueError):
        return fallback


@dataclass
class EntryQualityDecision:
    candidate_allowed: bool
    candidate_rank_score: float
    edge_after_cost_bps: float
    expected_move_bps: float
    cost_bps: float
    spread_bps: float
    liquidity_ok: bool
    recent_symbol_pnl: float | None = None
    recent_setup_pnl: float | None = None
    recent_churn_penalty: float = 0.0
    research_verdict: str = "not_checked"
    final_reason: str = "unknown"
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_allowed": self.candidate_allowed,
            "candidate_rank_score": self.candidate_rank_score,
            "edge_after_cost_bps": self.edge_after_cost_bps,
            "expected_move_bps": self.expected_move_bps,
            "cost_bps": self.cost_bps,
            "spread_bps": self.spread_bps,
            "liquidity_ok": self.liquidity_ok,
            "recent_symbol_pnl": self.recent_symbol_pnl,
            "recent_setup_pnl": self.recent_setup_pnl,
            "recent_churn_penalty": self.recent_churn_penalty,
            "research_verdict": self.research_verdict,
            "final_reason": self.final_reason,
            "evidence": self.evidence,
        }


class EntryQualityDecisionService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config or {}

    def decide(self, candidate: dict[str, Any]) -> dict[str, Any]:
        edge = _num(candidate.get("edge_after_cost_bps"), 0.0)
        expected = _num(candidate.get("expected_move_bps"), _num(candidate.get("expected_move_pct"), 0.0) * 100.0)
        spread_bps = _num(candidate.get("spread_bps"), _num(candidate.get("spread_pct"), 0.0) * 10000.0)
        cost_bps = _num(candidate.get("cost_bps"), max(0.0, expected - edge))
        min_edge = float(cfg_get(self.config, "push_pull.min_edge_after_cost_bps", 0.0) or 0.0)
        liquidity_ok = bool(candidate.get("liquidity_ok", True))
        quality = max(
            0.0,
            min(
                1.0,
                _num(candidate.get("trade_quality_score"), _num(candidate.get("quality_score"), 0.0)),
            ),
        )
        churn_penalty = _num(candidate.get("recent_churn_penalty"), 0.0)
        rank = max(0.0, quality + max(edge, 0.0) / 1000.0 - churn_penalty)
        allowed = liquidity_ok and edge > min_edge
        if not liquidity_ok:
            reason = "liquidity_weak_rotate"
        elif edge <= min_edge:
            reason = "no_edge_after_cost"
        else:
            reason = "positive_edge_after_cost"
        return EntryQualityDecision(
            candidate_allowed=allowed,
            candidate_rank_score=round(rank, 6),
            edge_after_cost_bps=round(edge, 4),
            expected_move_bps=round(expected, 4),
            cost_bps=round(cost_bps, 4),
            spread_bps=round(spread_bps, 4),
            liquidity_ok=liquidity_ok,
            recent_symbol_pnl=candidate.get("recent_symbol_pnl"),
            recent_setup_pnl=candidate.get("recent_setup_pnl"),
            recent_churn_penalty=round(churn_penalty, 6),
            research_verdict=str(candidate.get("research_verdict") or "not_checked"),
            final_reason=reason,
            evidence={"min_edge_after_cost_bps": min_edge},
        ).as_dict()
