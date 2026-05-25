"""Local qty with flat broker => ghost + entry blockers."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from sqlmodel import Session

from app.database import PositionSnapshot, engine, init_db
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.config_manager import ConfigManager


def main():
    init_db()
    with Session(engine) as session:
        session.add(
            PositionSnapshot(symbol="DOGEUSD", qty=50, avg_entry_price=0.1, current_price=0.1, synced_at=datetime.utcnow())
        )
        session.commit()

        with patch.object(BrokerReconciliationService, "sync_broker_snapshots", return_value=[]):
            svc = BrokerReconciliationService(session, ConfigManager(session).get_current())
            ghosts = svc.ghost_position_candidates()
            blockers = svc.training_entry_blockers()
        assert len(ghosts) >= 1
        assert any("ghost" in b for b in blockers)
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
