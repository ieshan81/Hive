from _alpha_factory_verify_common import seed_backtest, session_with_config

from sqlmodel import select

from app.database import AlphaScorecard
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_backtest(session)
    out = AutonomousAlphaFactoryService(session, cfg).run_candidate_promotion_cycle(operator="verify")
    rows = session.exec(select(AlphaScorecard)).all()
    assert out["scorecards_written"] >= 1, out
    assert rows and rows[0].verdict in ("paper_candidate", "promising", "unproven", "rejected"), rows
    print("verify_autonomous_cycle_writes_scorecards: PASS")
    print({"scorecards": len(rows), "verdict": rows[0].verdict})


if __name__ == "__main__":
    main()
