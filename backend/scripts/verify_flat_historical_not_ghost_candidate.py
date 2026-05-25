"""Broker-flat historical buy must not appear in ghost_position_candidates."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from sqlmodel import Session, select

from app.database import OrderRecord, PositionSnapshot, engine, init_db
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.config_manager import ConfigManager
from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop


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
            svc = BrokerReconciliationService(session, ConfigManager(session).get_current())
            ghosts = svc.ghost_position_candidates()
            blockers = svc.training_entry_blockers()
            ft = FastCryptoTrainingLoop(session).status()
        assert ghosts == [], f"expected no ghosts, got {ghosts}"
        assert "reconciliation:ghost_position_candidates" not in blockers
        assert ft.get("entries_eligible") is True
        assert ft.get("entries_allowed") is False
        assert ft.get("can_submit_orders") is False
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
