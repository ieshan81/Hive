"""No edge after cost is a normal no-trade decision, not an error state."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.services.entry_quality_decision_service import EntryQualityDecisionService


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        decision = EntryQualityDecisionService(
            session,
            {"push_pull": {"min_edge_after_cost_bps": 1.0}},
        ).decide(
            {
                "symbol": "BTC/USD",
                "trade_quality_score": 0.8,
                "edge_after_cost_bps": -2.0,
                "expected_move_bps": 8.0,
                "spread_bps": 1.0,
                "liquidity_ok": True,
            }
        )
    assert decision["candidate_allowed"] is False, decision
    assert decision["final_reason"] == "no_edge_after_cost", decision
    assert decision["edge_after_cost_bps"] == -2.0, decision
    print("verify_no_edge_means_no_trade_not_error: PASS")
    print({"candidate_allowed": decision["candidate_allowed"], "final_reason": decision["final_reason"]})


if __name__ == "__main__":
    main()
