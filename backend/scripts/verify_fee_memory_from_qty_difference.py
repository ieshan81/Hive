import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.memory_triggers import on_qty_fee_difference
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        row = on_qty_fee_difference(
            session,
            DEFAULT_CONFIG,
            filled_qty=293.366,
            broker_position_qty=292.633,
            symbol="DOGE/USD",
            cycle_run_id="test",
        )
        assert row is not None
        assert row.memory_type == "fee_lesson"
        print("verify_fee_memory_from_qty_difference: PASS")


if __name__ == "__main__":
    test()
