"""Verify crypto push-pull buy candidate gets explicit risk decision."""

from __future__ import annotations

from app.database import engine, Session, init_db, StrategySignal
from app.services.config_manager import ConfigManager
from app.services.risk_engine import RiskEngine, TradeProposal
from app.services.startup import bootstrap_database


def main() -> None:
    init_db()
    bootstrap_database()
    session = Session(engine)
    config = ConfigManager(session).get_current()
    risk = RiskEngine(session)

    proposal = TradeProposal(
        symbol="BTC/USD",
        side="buy",
        quantity=0.001,
        entry_price=100000.0,
        stop_loss=98000.0,
        take_profit=103000.0,
        strategy="crypto_push_pull",
        spread_pct=0.001,
        liquidity_score=80,
        asset_class="crypto",
        signal_confidence=0.65,
        signal_type="entry",
        expected_edge=0.01,
        volatility=0.03,
    )
    decision = risk.evaluate(proposal)
    assert decision.block_reason_code or decision.approved, "Must have explicit outcome"
    if not decision.approved:
        assert decision.human_reason and decision.risk_rule
        print("OK blocked with reason:", decision.block_reason_code, decision.human_reason)
    else:
        print("OK approved:", decision.block_reason_code)

    sell = TradeProposal(
        symbol="BTC/USD",
        side="sell",
        quantity=0.01,
        entry_price=100000.0,
        strategy="crypto_push_pull",
        asset_class="crypto",
        signal_type="exit",
        broker_position_qty=0,
    )
    d2 = risk.evaluate(sell)
    assert not d2.approved
    assert d2.block_reason_code == "SELL_BLOCKED_NO_BROKER_POSITION"
    print("OK sell without position blocked:", d2.human_reason)


if __name__ == "__main__":
    main()
