"""Verify negative momentum without position creates observation, not sell block."""

from __future__ import annotations

from app.database import engine, Session, init_db, StrategySignal, BlockedTrade
from app.services.config_manager import ConfigManager
from app.services.crypto_push_pull import CryptoPushPullStrategy
from app.services.startup import bootstrap_database
from sqlmodel import select


def main() -> None:
    init_db()
    bootstrap_database()
    session = Session(engine)
    config = ConfigManager(session).get_current()
    from app.services.alpaca_adapter import AlpacaAdapter

    alpaca = AlpacaAdapter(session)
    if not alpaca.configured:
        print("SKIP: Alpaca not configured")
        return

    cpp = CryptoPushPullStrategy(session, config, alpaca)
    cpp.cycle_run_id = "test-observation"
    positions = []
    sig = cpp.evaluate("BTC/USD", positions=positions, eligibility="eligible")
    if sig is None:
        print("SKIP: no signal (market data)")
        return

    assert sig.signal_type == "observation" or sig.status == "observation", sig.model_dump()
    assert sig.side != "sell" or sig.signal_type != "exit", "Must not create tradeable sell without position"

    blocked = session.exec(select(BlockedTrade).where(BlockedTrade.cycle_run_id == "test-observation")).all()
    assert len(blocked) == 0, "Observations must not create blocked_trades"

    print("OK no sell without position:", sig.signal_type, sig.status)


if __name__ == "__main__":
    main()
