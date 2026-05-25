"""Broker flat + historical buy => not active open position review."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from sqlmodel import Session

from sqlmodel import select

from app.database import OrderRecord, PositionSnapshot, engine, init_db
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.config_manager import ConfigManager


def main():
    init_db()
    with Session(engine) as session:
        for row in session.exec(select(PositionSnapshot)).all():
            session.delete(row)
        session.commit()
        session.add(
            OrderRecord(
                alpaca_order_id="buy-1",
                symbol="DOGE/USD",
                side="buy",
                qty=100,
                status="filled",
                filled_at=datetime.utcnow(),
            )
        )
        session.commit()
        with patch.object(BrokerReconciliationService, "sync_broker_snapshots", return_value=[]):
            audit = BrokerReconciliationService(session).classify_symbol("DOGE/USD")
        assert audit["classification"] == "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY"
        reviews = OpenPositionReviewService(session, ConfigManager(session).get_current()).review_all()
        assert reviews["count"] == 0
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
