"""Fresh broker-flat truth must repair stale trades even if PositionSnapshot is stale-open."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import PositionSnapshot, TradeRecord
from app.services.exposure_truth_service import ExposureTruthService
from app.services.trade_state_repair_service import TradeStateRepairService


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    original = ExposureTruthService.fresh_broker_positions
    ExposureTruthService.fresh_broker_positions = lambda self: ([], True, {"source": "fixture_fresh_broker_flat"})
    try:
        with Session(eng) as session:
            session.add(PositionSnapshot(symbol="DOGE/USD", qty=100, avg_entry_price=0.1, current_price=0.1))
            trade = TradeRecord(
                symbol="DOGE/USD",
                strategy="crypto_push_pull_baseline",
                side="buy",
                entry_price=0.1,
                quantity=100,
                status="open",
                opened_at=datetime.utcnow(),
            )
            session.add(trade)
            session.commit()
            out = TradeStateRepairService(session).repair_stale_open_trades_when_broker_flat(dry_run=False)
            session.commit()
            session.refresh(trade)
    finally:
        ExposureTruthService.fresh_broker_positions = original
    assert out["status"] == "ok", out
    assert out["affected_count"] == 1, out
    assert not any(s.get("reason") == "broker_position_open" for s in out.get("skipped", [])), out
    assert trade.status in ("broker_reconciled_flat", "closed_reconciled"), trade.status
    print("verify_fresh_broker_flat_repairs_stale_trade: PASS")
    print({"affected_count": out["affected_count"], "new_status": trade.status})


if __name__ == "__main__":
    main()
