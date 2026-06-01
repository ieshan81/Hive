"""Recent DOGE/UNI-style losses should quarantine the symbol briefly."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import PaperExperimentOutcome
from app.services.symbol_expectancy_guard_service import SymbolExpectancyGuardService


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    cfg = {"autonomous_paper_learning": {"recent_expectancy_guard": {"enabled": True}}}
    with Session(eng) as session:
        for pnl in (-0.04, -0.05):
            session.add(
                PaperExperimentOutcome(
                    strategy_id="crypto_push_pull_baseline",
                    symbol="DOGE/USD",
                    realized_pnl=pnl,
                    created_at=datetime.utcnow(),
                )
            )
        session.commit()
        out = SymbolExpectancyGuardService(session, cfg).evaluate("DOGE/USD", "crypto_push_pull_baseline")
    assert out["blocked"] is True, out
    assert out["reason"] == "RECENT_NEGATIVE_EXPECTANCY", out
    assert out["recent_trade_count"] == 2, out
    assert out["recent_gross_pnl"] <= -0.05, out
    print("verify_recent_negative_expectancy_blocks_symbol: PASS")
    print({"reason": out["reason"], "recent_gross_pnl": out["recent_gross_pnl"]})


if __name__ == "__main__":
    main()
