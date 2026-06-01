"""Applying stale local trade repair never deletes history or fakes P&L."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.database  # noqa: F401
from app.database import AccountSnapshot, OrderRecord, TradeRecord
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
            entry_price=0.10,
            quantity=100,
            status="open",
            opened_at=datetime.utcnow(),
        )
        session.add(trade)
        session.add(
            OrderRecord(
                symbol="DOGE/USD",
                side="sell",
                qty=100,
                status="filled",
                filled_at=datetime.utcnow(),
                filled_avg_price=0.12,
            )
        )
        session.commit()
        out = TradeStateRepairService(session).repair_stale_open_trades_when_broker_flat(dry_run=False)
        session.commit()
        repaired = session.get(TradeRecord, trade.id)
        trade_count = len(session.exec(select(TradeRecord)).all())
    assert out["status"] == "ok", out
    assert out["affected_count"] == 1, out
    assert trade_count == 1, trade_count
    assert repaired is not None and repaired.status == "closed_reconciled", repaired
    assert round(float(repaired.pl_dollars or 0), 6) == 2.0, repaired.pl_dollars
    print("verify_stale_trade_repair_apply: PASS")
    print({"new_status": repaired.status, "pl_dollars": repaired.pl_dollars, "records_deleted": out["records_deleted"]})


if __name__ == "__main__":
    main()
