"""Promotion exploration_candidate -> paper_candidate requires real evidence: >= 20 closed
exploration trades, positive after-cost expectancy, and profit factor > 1.10. Fewer than 20
closed trades can NEVER promote, no matter how good the early sample looks."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import PaperExperimentOutcome  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402

SYM, SID = "UNI/USD", "session_new_york_opening_range_breakout"


def _add(session, pnl, n=1):
    for _ in range(n):
        session.add(PaperExperimentOutcome(strategy_id=SID, symbol=SYM, realized_pnl=pnl, exit_reason="x"))
    session.commit()


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    # 19 strongly positive closed trades -> STILL cannot promote (below the 20 gate).
    _add(session, 0.5, n=19)
    g = svc.can_promote_from_exploration(SYM, SID)
    assert g["closed_trades"] == 19, g
    assert g["can_promote"] is False, g
    assert any("20" in r for r in g["reasons"]), g

    # 20th closed trade, positive expectancy + PF > 1.10 -> now promotable on evidence.
    _add(session, 0.5, n=1)
    # Add a couple of small losers so PF is finite and computed (still > 1.10).
    _add(session, -0.1, n=2)
    g2 = svc.can_promote_from_exploration(SYM, SID)
    assert g2["closed_trades"] >= 20, g2
    assert g2["expectancy"] and g2["expectancy"] > 0, g2
    assert g2["profit_factor"] and g2["profit_factor"] > 1.10, g2
    assert g2["can_promote"] is True, g2
    print(f"verify_paper_exploration_cannot_promote_without_20_closed_trades: PASS "
          f"(<20 blocked; {g2['closed_trades']} closed pf={g2['profit_factor']} -> promotable)")


if __name__ == "__main__":
    main()
