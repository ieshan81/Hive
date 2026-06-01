"""An eligible near-miss becomes a paper_exploration_candidate (a stage BELOW paper_candidate).

It is never a tradeable verdict and an insufficient-evidence near-miss is not eligible.
"""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.autonomous_alpha_promotion_service import PAPER_ALLOWED_VERDICTS  # noqa: E402
from app.services.paper_exploration_service import EXPLORATION_STAGE, PaperExplorationService  # noqa: E402


def nm(**over):
    base = dict(
        id=1, symbol="UNI/USD", strategy_id="session_new_york_opening_range_breakout",
        strategy_family="new_york_opening_range_breakout", verdict="unproven",
        sample_size=60, session_sample_size=137, edge_after_cost_bps=-2.0, session_edge_after_cost_bps=0.82,
        cost_bps=20.0, spread_bps=8.0, fee_bps=25.0, profit_factor=1.0, max_drawdown_pct=6.0,
        data_freshness_status="fresh", recent_loss_cooldown_until=None,
        best_session="new_york_session", session_metrics_available=True,
    )
    base.update(over)
    return base


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)

    e = svc.evaluate(nm())
    assert e["exploration_eligible"] is True, e
    assert e["exploration_stage"] == EXPLORATION_STAGE, e
    assert e["exploration_score"] > 0, e
    assert not e["exploration_blockers"], e

    # The exploration stage is NOT a tradeable verdict — it sits below paper_candidate.
    assert EXPLORATION_STAGE not in PAPER_ALLOWED_VERDICTS, EXPLORATION_STAGE

    # Insufficient sample / already-a-candidate are not eligible.
    assert svc.evaluate(nm(sample_size=10, session_sample_size=10))["exploration_eligible"] is False
    assert svc.evaluate(nm(verdict="paper_candidate"))["exploration_eligible"] is False
    print("verify_near_miss_can_be_paper_exploration_candidate: PASS")


if __name__ == "__main__":
    main()
