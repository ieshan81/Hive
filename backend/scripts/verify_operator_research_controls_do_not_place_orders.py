from _alpha_factory_verify_common import session_with_config

from sqlmodel import select

from app.database import OrderRecord
from app.services.autonomous_alpha_scheduler import AutonomousAlphaScheduler


def main() -> None:
    session, cfg = session_with_config()
    before = len(session.exec(select(OrderRecord)).all())
    out = AutonomousAlphaScheduler(session, cfg).run_due(operator="verify", force=True)
    after = len(session.exec(select(OrderRecord)).all())
    assert before == after == 0, (before, after, out)
    assert out.get("orders_created") == 0, out
    print("verify_operator_research_controls_do_not_place_orders: PASS")
    print({"status": out["status"], "orders_after": after})


if __name__ == "__main__":
    main()
