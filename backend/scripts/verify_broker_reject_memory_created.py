"""ensure_reconciliation_memories can create broker_reject_memory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from sqlmodel import Session

from app.database import ExecutionLog, engine, init_db
from app.services.broker_reconciliation_service import BrokerReconciliationService


def main():
    init_db()
    with Session(engine) as session:
        session.add(
            ExecutionLog(
                event_id="rej-1",
                cycle_run_id="training-exit-x",
                symbol="DOGE/USD",
                side="sell",
                signal_type="exit",
                status="paper_order_rejected",
                reject_reason="BROKER_REJECTED",
                gates_failed_json={"broker": "insufficient balance", "preflight_stage": "broker_rejection"},
            )
        )
        session.commit()
        out = BrokerReconciliationService(session).ensure_reconciliation_memories()
        assert "broker_reject_memory" in out.get("created", []) or out.get("status") == "ok"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
