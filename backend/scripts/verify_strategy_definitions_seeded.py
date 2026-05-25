import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from sqlmodel import Session
from app.services.strategy_library import seed_strategy_library, list_strategies


def main():
    init_db()
    with Session(engine) as session:
        n = seed_strategy_library(session, force_update=True)
        session.commit()
        rows = list_strategies(session)
        assert len(rows) >= 10, f"expected >=10 strategies, got {len(rows)}"
        ids = {r["strategy_id"] for r in rows}
        assert "crypto_push_pull_momentum" in ids
        print("verify_strategy_definitions_seeded: OK", len(rows), "definitions")


if __name__ == "__main__":
    main()
