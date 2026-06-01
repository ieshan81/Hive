"""Exploration tracks closed-trade outcomes (count, expectancy, profit factor) so a verdict
can be formed from REAL evidence rather than the session signal alone."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import PaperExperimentOutcome  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402

SYM, SID = "UNI/USD", "session_new_york_opening_range_breakout"


def _outcome(pnl):
    return PaperExperimentOutcome(strategy_id=SID, symbol=SYM, realized_pnl=pnl, exit_reason="take_profit" if pnl > 0 else "stop_loss")


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    # No closed trades yet.
    g0 = svc.can_promote_from_exploration(SYM, SID)
    assert g0["closed_trades"] == 0, g0
    assert g0["can_promote"] is False, g0

    # Record a mix of closed exploration outcomes.
    for pnl in [0.4, 0.5, -0.2, 0.3, -0.1]:
        session.add(_outcome(pnl))
    session.commit()

    g1 = svc.can_promote_from_exploration(SYM, SID)
    assert g1["closed_trades"] == 5, g1
    assert g1["expectancy"] is not None, g1
    assert g1["profit_factor"] is not None, g1
    # Still below the 20-closed-trade gate -> cannot promote.
    assert g1["can_promote"] is False, g1
    assert any("closed_trades" in r for r in g1["reasons"]), g1
    print(f"verify_paper_exploration_tracks_outcomes: PASS (closed={g1['closed_trades']}, pf={g1['profit_factor']})")


if __name__ == "__main__":
    main()
