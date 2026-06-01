"""The session-aware run cycle refreshes scorecards/sessions/memory but places NO orders.

run_autonomous_cycle now includes a session_backfill phase. It must refresh session metrics
and write session memory while creating zero broker orders / execution logs and never forcing
a paper_candidate.
"""

from _alpha_factory_verify_common import seed_backtest, seed_session_bars, session_with_config  # noqa: E402

from sqlmodel import func, select  # noqa: E402

from app.database import AlphaScorecard, ExecutionLog, OrderRecord  # noqa: E402
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService  # noqa: E402


def _orders(s) -> int:
    return int(s.exec(select(func.count()).select_from(OrderRecord)).one() or 0) + int(
        s.exec(select(func.count()).select_from(ExecutionLog)).one() or 0
    )


def main() -> None:
    session, cfg = session_with_config()
    seed_session_bars(session, symbol="BTC/USD", utc_hour=14, n=10, direction=0.6)
    seed_backtest(session, symbol="BTC/USD", strategy_id="session_london_ny_overlap_continuation", trades=10)
    before = _orders(session)
    svc = AutonomousAlphaFactoryService(session, cfg)
    out = svc.run_autonomous_cycle({"symbols": ["BTC/USD"], "symbol_limit": 2, "candidate_limit": 2})
    session.commit()
    after = _orders(session)

    phases = {p.get("phase") for p in out.get("phases", [])}
    assert "session_backfill" in phases, f"session_backfill phase missing: {phases}"
    # ORDER SAFETY: the research cycle places zero broker orders / execution logs, even when a
    # candidate qualifies — Alpha Factory has no order authority; only the cage submits orders.
    assert out.get("orders_created") == 0, out
    assert out.get("research_only") is True, out
    assert after == before == 0, (before, after)

    # The cycle backfilled session metrics on the scorecard(s) it built.
    cards = list(session.exec(select(AlphaScorecard)).all())
    assert any(c.best_session for c in cards), "expected at least one scorecard with session metrics"
    # Any qualified candidate came from FULL sample evidence (not a session signal alone).
    min_sample = int(cfg.get("alpha_factory", {}).get("min_sample_size", 5) or 5)
    for c in cards:
        if c.verdict in ("paper_candidate", "paper_active"):
            assert (c.sample_size or 0) >= min_sample, f"candidate {c.symbol} promoted without full sample: {c.sample_size}"
    print("verify_session_run_cycle_never_places_orders: PASS")


if __name__ == "__main__":
    main()
