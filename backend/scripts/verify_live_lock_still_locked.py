"""Live lock remains locked in reconciliation paths."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.config_manager import ConfigManager
from app.services.live_lock_tripwire import live_lock_tripwire_status


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        assert live_lock_tripwire_status(cfg).get("live_lock_status") == "locked"
        eo = BrokerReconciliationService(session, cfg).exit_only_reconciliation_status()
        assert eo.get("exit_only", {}).get("live_lock_status") == "locked"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
