"""Dry-run stale local trade repair reports actions but does not mutate history."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import AccountSnapshot, TradeRecord
from app.services.exposure_truth_service import ExposureTruthService
from app.services.trade_state_repair_service import TradeStateRepairService


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(AccountSnapshot(equity=200, cash=200, buying_power=200, portfolio_value=200))
        trade = TradeRecord(
            symbol="DOGE/USD",
            strategy="fixture",
            side="buy",
            entry_price=0.1,
            quantity=100,
            status="open",
            opened_at=datetime.utcnow(),
        )
        session.add(trade)
        session.commit()
        original = ExposureTruthService.fresh_broker_positions
        ExposureTruthService.fresh_broker_positions = lambda self: ([], True, {"source": "fixture_fresh_broker_flat"})
        try:
            out = TradeStateRepairService(session).repair_stale_open_trades_when_broker_flat(dry_run=True)
        finally:
            ExposureTruthService.fresh_broker_positions = original
        session.refresh(trade)
    assert out["status"] == "ok", out
    assert out["dry_run"] is True and out["affected_count"] == 1, out
    assert trade.status == "open", trade.status
    print("verify_stale_trade_repair_dry_run: PASS")
    print({"affected_count": out["affected_count"], "trade_status": trade.status})


if __name__ == "__main__":
    main()
