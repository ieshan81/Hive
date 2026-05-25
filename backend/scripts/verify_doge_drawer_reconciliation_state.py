"""Hive brain DOGE drawer exposes reconciliation_state when flat."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from sqlmodel import Session

from app.database import OrderRecord, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.hive_brain_node_service import HiveBrainNodeService


def main():
    init_db()
    with Session(engine) as session:
        session.add(
            OrderRecord(
                alpaca_order_id="buy-doge",
                symbol="DOGE/USD",
                side="buy",
                qty=10,
                status="filled",
                filled_at=datetime.utcnow(),
            )
        )
        session.commit()
        from app.services.broker_reconciliation_service import BrokerReconciliationService

        with patch.object(BrokerReconciliationService, "sync_broker_snapshots", return_value=[]):
            out = HiveBrainNodeService(session, ConfigManager(session).get_current()).get_node(
                "position-DOGEUSD"
            )
        ev = out["node"]["sections"]["evidence"]
        assert ev.get("reconciliation_state") == "broker_flat_historical_order_only"
        assert "historical" in out["node"]["title"].lower() or "flat" in out["node"]["title"].lower()
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
