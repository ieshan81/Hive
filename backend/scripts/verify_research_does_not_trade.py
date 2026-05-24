import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine, OrderRecord
from sqlmodel import Session, select
from app.services.research_lab_service import ResearchLabService


def main():
    init_db()
    with Session(engine) as session:
        orders_before = len(session.exec(select(OrderRecord)).all())
        ResearchLabService(session).run_research_batch({"strategy_families": ["mean_reversion"], "symbols": ["BTC/USD"]})
        session.commit()
        orders_after = len(session.exec(select(OrderRecord)).all())
        assert orders_before == orders_after, "research must not create orders"
        print("verify_research_does_not_trade: OK")


if __name__ == "__main__":
    main()
