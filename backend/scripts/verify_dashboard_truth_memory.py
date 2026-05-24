import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.memory_triggers import on_dashboard_truth_mismatch
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        row = on_dashboard_truth_mismatch(
            session,
            DEFAULT_CONFIG,
            dashboard_field="approvalMessage",
            dashboard_value="No tradeable signals",
            truth_value={"orders_submitted": 1},
            cycle_run_id="8796825e-5f25-4cfa-b0f9-b0141f61859c",
        )
        session.commit()
        assert row.memory_type == "ui_truth_bug"
        assert row.category == "system_issue"
        assert row.can_influence_ranking is False
        print("verify_dashboard_truth_memory: PASS")


if __name__ == "__main__":
    test()
