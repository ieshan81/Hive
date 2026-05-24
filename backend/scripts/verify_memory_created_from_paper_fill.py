import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import ExecutionLog, init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.memory_triggers import on_paper_order_filled
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        log = ExecutionLog(
            event_id="test",
            cycle_run_id="test-cycle",
            symbol="DOGE/USD",
            side="buy",
            signal_type="entry",
            status="paper_order_filled",
            filled_qty=293.0,
            filled_avg_price=0.102282,
            broker_order_id="test-broker",
            broker_client_order_id="CHQ-test",
        )
        row = on_paper_order_filled(session, config=DEFAULT_CONFIG, execution_log=log, cycle_run_id="test-cycle")
        session.commit()
        assert row.memory_type == "trade_lesson"
        print("verify_memory_created_from_paper_fill: PASS")


if __name__ == "__main__":
    test()
