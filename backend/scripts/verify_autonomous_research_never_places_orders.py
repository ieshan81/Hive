from _alpha_factory_verify_common import seed_backtest, session_with_config

from sqlmodel import select

from app.database import OrderRecord
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_backtest(session)
    before = len(session.exec(select(OrderRecord)).all())
    out = AutonomousAlphaFactoryService(session, cfg).run_autonomous_cycle({"candidate_limit": 0}, operator="verify")
    session.commit()
    after = len(session.exec(select(OrderRecord)).all())
    assert before == after == 0, (before, after, out)
    assert out.get("orders_created") == 0, out
    print("verify_autonomous_research_never_places_orders: PASS")
    print({"orders_before": before, "orders_after": after, "status": out["status"]})


if __name__ == "__main__":
    main()
