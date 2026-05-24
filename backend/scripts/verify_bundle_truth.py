"""Verify diagnostic bundle counts match a synthetic cycle write."""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.database import engine, init_db, StrategySignal
from app.services.activity_logger import log_activity
from app.services.cycle_persistence import count_cycle_rows, verify_cycle_persistence
from app.services.diagnostic_export import export_diagnostic_bundle
from app.services.startup import bootstrap_database
from app.services.risk_engine import RiskEngine, TradeProposal


def main() -> None:
    init_db()
    bootstrap_database()
    cycle_run_id = str(uuid.uuid4())
    session = Session(engine)

    # Simulate 4 created signals, all blocked
    signals: list[StrategySignal] = []
    for i in range(4):
        sig = StrategySignal(
            strategy="crypto_night_momentum",
            symbol=f"BTC/USD",
            asset_class="crypto",
            signal="buy",
            side="buy",
            strength=0.7,
            confidence=0.55,
            status="generated",
            cycle_run_id=cycle_run_id,
        )
        session.add(sig)
        signals.append(sig)
    session.commit()
    for sig in signals:
        session.refresh(sig)

    risk = RiskEngine(session)
    for sig in signals:
        proposal = TradeProposal(
            symbol=sig.symbol,
            side="buy",
            quantity=0.01,
            strategy=sig.strategy,
            signal_id=sig.id,
            cycle_run_id=cycle_run_id,
            signal_confidence=sig.confidence,
            asset_class="crypto",
            spread_pct=0.01,
        )
        decision = risk.evaluate(proposal)
        assert not decision.approved
        assert decision.block_reason_code
        assert decision.human_reason

    summary = {
        "cycle_run_id": cycle_run_id,
        "signals_created": 4,
        "signals_generated": 4,
        "blocked": 4,
        "approved": 0,
        "status": "ok",
        "started_at": "2099-01-01T00:00:00Z",
        "account_synced": False,
        "alpaca_configured": False,
    }
    verify_cycle_persistence(session, summary)
    log_activity(
        session,
        "cycle_end",
        "Synthetic cycle complete",
        {**summary, "ended_at": "2099-01-01T00:00:00Z", "status": "ok"},
    )
    session.commit()
    assert summary["persistence"]["signals_match"]
    assert summary["persistence"]["blocked_match"]
    assert summary["persistence"]["risk_events_match"]

    bundle = export_diagnostic_bundle(session)
    assert len(bundle["strategy_signals.json"]) == 4, bundle["strategy_signals.json"]
    assert len(bundle["blocked_trades.json"]) == 4
    assert len(bundle["risk_events.json"]) == 4
    for row in bundle["strategy_signals.json"]:
        assert row.get("id") is not None
        assert row.get("symbol")
        assert row.get("strategy_name")
    for row in bundle["risk_events.json"]:
        assert row.get("id") is not None
        assert row.get("block_reason_code")
    for row in bundle["activity.json"]:
        assert row.get("id") is not None
        assert row.get("event_type")
    assert "Status: ok" in bundle["system_summary.md"] or "Status: partial" in bundle["system_summary.md"]
    for row in bundle["blocked_trades.json"]:
        assert row.get("block_reason_code")
        assert row.get("human_reason")
        assert row.get("risk_rule")
        assert row.get("evidence_json")
        assert row.get("risk_engine_result")

    counts = count_cycle_rows(session, cycle_run_id)
    print("OK bundle truth:", counts)
    session.close()


if __name__ == "__main__":
    main()
