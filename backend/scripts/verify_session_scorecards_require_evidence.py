"""Session-specific strategy variants only become scorecards from real evidence, and an
insufficient session sample never becomes a paper_candidate.

Covers the four session families: london_session_momentum, new_york_opening_range_breakout,
london_new_york_overlap_continuation, liquidity_sweep_reversal.
"""

from _alpha_factory_verify_common import seed_session_bars, session_with_config  # noqa: E402

from app.database import ResearchBacktestRun  # noqa: E402
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService  # noqa: E402

PAPER_ALLOWED = ("paper_candidate", "paper_active")

SESSION_VARIANTS = [
    ("session_london_momentum", "london_session_momentum"),
    ("session_new_york_opening_range_breakout", "new_york_opening_range_breakout"),
    ("session_london_ny_overlap_continuation", "london_new_york_overlap_continuation"),
    ("session_liquidity_sweep_reversal", "liquidity_sweep_reversal"),
]


def _seed_run(session, strategy_id, symbol, *, trades, exp, pf):
    session.add(ResearchBacktestRun(
        run_id=f"rt_{strategy_id}", strategy_id=strategy_id, symbols=[symbol], status="completed",
        num_trades=trades, sample_size=trades, source="autonomous_research_worker",
        metrics_json={"win_rate": 0.6, "expectancy": exp, "profit_factor": pf, "max_drawdown_pct": 5.0, "timeframe": "5Min"},
    ))


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="LINK/USD", utc_hour=14, n=12, direction=0.7)
    # Each session variant has only a thin (insufficient) sample even though core is positive.
    for sid, _fam in SESSION_VARIANTS:
        _seed_run(session, sid, "LINK/USD", trades=2, exp=0.01, pf=1.5)
    session.commit()

    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.bootstrap_scorecards_from_existing_evidence()
    session.commit()

    cards = svc.get_scorecards(limit=200)["scorecards"]
    by_sid = {c["strategy_id"]: c for c in cards}
    for sid, fam in SESSION_VARIANTS:
        assert sid in by_sid, f"no scorecard created for session variant {sid} (evidence existed)"
        card = by_sid[sid]
        assert card["strategy_family"] == fam, (sid, card["strategy_family"])
        # Insufficient session/overall sample -> never a tradeable candidate.
        assert card["verdict"] not in PAPER_ALLOWED, (sid, card["verdict"])

    # No paper candidates at all from thin session evidence.
    assert not any(c["verdict"] in PAPER_ALLOWED for c in cards), [c["verdict"] for c in cards]
    print("verify_session_scorecards_require_evidence: PASS")


if __name__ == "__main__":
    main()
