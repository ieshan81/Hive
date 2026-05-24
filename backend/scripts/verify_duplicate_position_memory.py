import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.memory_triggers import on_duplicate_position_export
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        row = on_duplicate_position_export(
            session,
            DEFAULT_CONFIG,
            symbol="DOGE/USD",
            duplicate_count=2,
            broker_positions_count=1,
            exported_count=2,
            cycle_run_id="8796825e-5f25-4cfa-b0f9-b0141f61859c",
        )
        session.commit()
        assert row.memory_type == "reconciliation_bug"
        assert row.category == "system_issue"
        assert row.evidence_json.get("duplicate_count") == 2
        print("verify_duplicate_position_memory: PASS")


if __name__ == "__main__":
    test()
