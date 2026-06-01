"""Backfill fills session metrics on pre-existing scorecards from candle evidence.

Mirrors the prod gap: scorecards created before session-aware research (PR #21) have no
session_* fields. backfill_session_metrics must populate them from candles, mark an explained
absence when there is no timestamped evidence, and NEVER change the verdict (session signal
alone never promotes) or place orders. Idempotent.
"""

from _alpha_factory_verify_common import seed_session_bars, session_with_config  # noqa: E402

from sqlmodel import select  # noqa: E402

from app.database import AlphaScorecard  # noqa: E402
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService  # noqa: E402


def _mk(symbol, norm, *, verdict, sample, exp):
    return AlphaScorecard(
        symbol=symbol, normalized_symbol=norm, asset_class="crypto",
        strategy_family="momentum_continuation", strategy_id="crypto_push_pull_baseline",
        timeframe="5Min", sample_size=sample, expectancy=exp, profit_factor=0.8,
        max_drawdown_pct=5.0, cost_bps=10.0, spread_bps=3.0, slippage_bps=2.0, fee_bps=0.0,
        edge_after_cost_bps=(exp or 0) * 10000.0, verdict=verdict, scorecard_json={},
    )


def main() -> None:
    session, cfg = session_with_config()
    # Candle evidence exists for BTC/USD (London/NY overlap window); NONE for ZZZ/USD.
    seed_session_bars(session, symbol="BTC/USD", utc_hour=14, n=10, direction=0.6)
    session.add(_mk("BTC/USD", "BTCUSD", verdict="rejected", sample=20, exp=-0.01))
    session.add(_mk("ZZZ/USD", "ZZZUSD", verdict="unproven", sample=0, exp=None))
    session.commit()

    svc = AutonomousAlphaFactoryService(session, cfg)
    before = {c.symbol: c.verdict for c in session.exec(select(AlphaScorecard)).all()}
    out = svc.backfill_session_metrics(force=True)
    session.commit()
    cards = {c.symbol: c for c in session.exec(select(AlphaScorecard)).all()}

    # BTC: real session metrics filled.
    btc = cards["BTC/USD"]
    assert btc.best_session, f"BTC best_session not filled: {btc.best_session}"
    assert (btc.session_sample_size or 0) > 0, btc.session_sample_size
    btc_sm = (btc.scorecard_json or {}).get("session_metrics", {})
    assert btc_sm.get("session_metrics_available") is True, btc_sm
    assert btc.session_edge_after_cost_bps is not None, btc.session_edge_after_cost_bps

    # ZZZ: no candle evidence -> explained absence, scorecard otherwise unchanged.
    zzz = cards["ZZZ/USD"]
    zzz_sm = (zzz.scorecard_json or {}).get("session_metrics", {})
    assert zzz_sm.get("session_metrics_available") is False, zzz_sm
    assert zzz_sm.get("session_metrics_reason") == "no_timestamped_trade_evidence", zzz_sm
    assert zzz.best_session is None, zzz.best_session

    # Safety invariants: verdicts unchanged, no orders.
    after = {c.symbol: c.verdict for c in session.exec(select(AlphaScorecard)).all()}
    assert before == after, (before, after)
    assert out["orders_created"] == 0, out
    assert out["session_metrics_available"] == 1 and out["session_metrics_unavailable"] == 1, out

    # Idempotent: force=False is a no-op once everything is marked.
    out2 = svc.backfill_session_metrics(force=False)
    assert out2["scorecards_seen"] == 0, out2
    print("verify_session_metrics_backfill_existing_scorecards: PASS")


if __name__ == "__main__":
    main()
