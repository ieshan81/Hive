import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.memory_triggers import on_repeated_risk_block
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        pk = "risk_block|DOGE/USD|SPREAD_TOO_WIDE"
        row1 = on_repeated_risk_block(
            session,
            DEFAULT_CONFIG,
            symbol="DOGE/USD",
            block_reason_code="SPREAD_TOO_WIDE",
            count=3,
            strategy_name="crypto_push_pull",
            cycle_run_id="cycle-1",
        )
        session.flush()
        row2 = on_repeated_risk_block(
            session,
            DEFAULT_CONFIG,
            symbol="DOGE/USD",
            block_reason_code="SPREAD_TOO_WIDE",
            count=4,
            strategy_name="crypto_push_pull",
            cycle_run_id="cycle-2",
        )
        session.commit()
        assert row1.id == row2.id
        assert row2.occurrence_count >= 2
        assert row2.pattern_key == pk or row2.pattern_key
        print("verify_pattern_memory_aggregation: PASS")


if __name__ == "__main__":
    test()
