"""Exploration respects broker truth: an open position in the same symbol blocks exploring it,
and the position cap blocks new probes."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import PositionSnapshot  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from scripts.verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    # No positions -> eligible + allowed.
    assert svc.evaluate(nm())["exploration_eligible"] is True
    assert svc.permission()["paper_exploration_allowed"] is True

    # Open a broker position in the same symbol.
    session.add(PositionSnapshot(symbol="UNI/USD", qty=1.0))
    session.commit()

    e = svc.evaluate(nm(symbol="UNI/USD"))
    assert "open_broker_position_same_symbol" in e["exploration_blockers"], e
    assert e["exploration_eligible"] is False, e

    # Position cap (default 1) blocks new exploration entries.
    perm = svc.permission()
    assert perm["paper_exploration_allowed"] is False, perm
    assert "exploration_max_positions" in str(perm["paper_exploration_block_reason"]), perm
    print("verify_paper_exploration_respects_broker_position: PASS")


if __name__ == "__main__":
    main()
