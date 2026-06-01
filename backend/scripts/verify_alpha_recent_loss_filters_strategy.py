"""Strategy-filtered recent-loss cooldown must not cross-contaminate strategies."""

from __future__ import annotations

from datetime import datetime

from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.database import TradeRecord
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    symbol = "DOGE/USD"
    strategy_a = "crypto_push_pull_baseline"
    strategy_b = "crypto_mean_reversion_snapback_v1"

    for idx in range(2):
        session.add(
            TradeRecord(
                symbol=symbol,
                strategy=strategy_a,
                side="buy",
                entry_price=0.10,
                exit_price=0.08,
                quantity=100,
                pl_dollars=-2.5 - idx,
                status="closed",
                closed_at=datetime.utcnow(),
            )
        )
    session.commit()

    run_b = seed_backtest(session, symbol=symbol, strategy_id=strategy_b, run_id="bt_strategy_b")
    svc = AutonomousAlphaFactoryService(session, cfg)
    recent_b = svc._recent_paper(symbol, strategy_b)

    assert recent_b["strategy_filter_applied"] is True, recent_b
    assert recent_b["skipped_other_strategy_trade_count"] >= 2, recent_b
    assert recent_b["count"] == 0, recent_b
    assert recent_b.get("cooldown_until") is None, recent_b

    sc = svc._scorecard_from_backtest(run_b, symbol)
    session.commit()
    evidence = (sc.scorecard_json or {}).get("recent_loss_evidence") or {}
    assert evidence.get("strategy_filter_applied") is True, evidence
    assert evidence.get("skipped_other_strategy_trade_count", 0) >= 2, evidence

    svc.run_candidate_promotion_cycle(operator="verify")
    gate = svc.can_trade_paper(symbol, strategy_id=strategy_b)
    assert gate["allowed"] is True or "cooldown" not in str(gate.get("reason")), gate

    print("verify_alpha_recent_loss_filters_strategy: PASS")
    print({"strategy_b_recent": recent_b, "gate": gate["reason"]})


if __name__ == "__main__":
    main()
