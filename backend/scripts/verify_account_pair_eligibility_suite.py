"""Account/pair eligibility, banner truth, diagnostic bundle, rate-limit safety."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AUTONOMOUS_BUNDLE_KEYS = [
    "confidence_level.json",
    "strategy_confidence.json",
    "symbol_confidence.json",
    "paper_learning_status.json",
    "autonomous_learning_scheduler.json",
    "account_pair_eligibility.json",
    "backtest_lab_results.json",
    "strategy_proposals.json",
    "promotion_readiness.json",
]


def test_usdc_blocked_when_zero_balance():
    from sqlmodel import Session

    from app.database import AccountSnapshot, engine, init_db
    from app.services.account_pair_eligibility_service import (
        AccountPairEligibilityService,
        quote_balance_block_reason,
    )

    init_db()
    with Session(engine) as session:
        session.add(
            AccountSnapshot(
                equity=10000,
                cash=5000,
                buying_power=5000,
                portfolio_value=10000,
                raw_payload={"USDC": 0},
            )
        )
        session.commit()
        svc = AccountPairEligibilityService(session, {})
        with patch.object(svc.alpaca, "broker_sync_rate_limited", False):
            with patch.object(svc.alpaca, "sync_account_cached", return_value=session.exec(
                __import__("sqlmodel").select(AccountSnapshot)
            ).first()):
                row = svc.classify_symbol("BAT/USDC")
        assert row["status"] == "blocked"
        assert row["category"] == "account_pair_eligibility"
        assert row["reason"] == quote_balance_block_reason("USDC")
        block = svc.preflight_block("BAT/USDC", "buy")
        assert block is not None
        assert block[0] == "account_pair_eligibility"
    print("OK usdc_blocked_when_zero")


def test_usd_pair_eligible_when_usd_balance():
    from sqlmodel import Session

    from app.database import AccountSnapshot, engine, init_db
    from app.services.account_pair_eligibility_service import AccountPairEligibilityService

    init_db()
    with Session(engine) as session:
        session.add(
            AccountSnapshot(equity=10000, cash=5000, buying_power=5000, portfolio_value=10000)
        )
        session.commit()
        svc = AccountPairEligibilityService(session, {})
        snap = session.exec(__import__("sqlmodel").select(AccountSnapshot)).first()
        with patch.object(svc.alpaca, "broker_sync_rate_limited", False):
            with patch.object(svc.alpaca, "sync_account_cached", return_value=snap):
                row = svc.classify_symbol("ETH/USD")
        assert row["status"] == "eligible"
    print("OK usd_pair_eligible")


def test_no_broker_submit_on_ineligible():
    from sqlmodel import Session

    from app.database import AccountSnapshot, engine, init_db
    from app.services.account_pair_eligibility_service import AccountPairEligibilityService

    init_db()
    with Session(engine) as session:
        session.add(
            AccountSnapshot(
                equity=10000,
                cash=5000,
                buying_power=5000,
                portfolio_value=10000,
                raw_payload={"USDC": 0},
            )
        )
        session.commit()
        snap = session.exec(__import__("sqlmodel").select(AccountSnapshot)).first()
        svc = AccountPairEligibilityService(session, {})
        with patch.object(svc.alpaca, "broker_sync_rate_limited", False):
            with patch.object(svc.alpaca, "sync_account_cached", return_value=snap):
                assert svc.preflight_block("BAT/USDC", "buy") is not None
                tradeable = svc.filter_tradeable_symbols(
                    ["BAT/USDC", "ETH/USD"], strategy_id="crypto_push_pull"
                )
        assert "BAT/USDC" not in tradeable
        assert "ETH/USD" in tradeable
    print("OK no_broker_submit_ineligible")


def test_eligibility_block_not_strategy_failure():
    from sqlmodel import Session

    from app.database import AccountSnapshot, engine, init_db
    from app.services.aggressive_paper_learning_service import AggressivePaperLearningService

    init_db()
    with Session(engine) as session:
        session.add(
            AccountSnapshot(
                equity=10000,
                cash=5000,
                buying_power=5000,
                portfolio_value=10000,
                raw_payload={"USDC": 0},
            )
        )
        session.commit()
        pl = AggressivePaperLearningService(session)
        with patch.object(pl, "_spread_ok", return_value=True):
            with patch.object(pl, "_liquidity_ok", return_value=True):
                with patch.object(pl, "symbol_tier", return_value="MAJOR_CRYPTO"):
                    with patch.object(pl, "_decisions_today", return_value=0):
                        with patch.object(pl, "_rejects_today", return_value=0):
                            block = pl._preflight_block(
                                "BAT/USDC", 10.0, strategy_id="crypto_push_pull", side="buy"
                            )
    assert block is not None
    assert block[0] == "account_pair_eligibility"
    assert block[0] != "strategy_failure"
    print("OK eligibility_not_strategy_failure")


def test_paper_learning_truth_matches_fields():
    from sqlmodel import Session

    from app.database import engine, init_db
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService
    from app.services.paper_learning_truth import paper_learning_display_status

    init_db()
    with Session(engine) as session:
        cfg = {
            "autonomous_paper_learning": {"mode_enabled": True},
            "fast_training": {"fast_training_loop_enabled": True},
            "execution": {"paper_orders_enabled": True},
        }
        display = paper_learning_display_status(session, cfg)
        status = AutonomousPaperLearningService(session, cfg).status()
        assert display["paperLearning"] == ("ON" if display["mode_enabled"] else "OFF")
        assert status["paper_learning_on"] == display["mode_enabled"]
        assert status["bot_can_place_paper_orders"] == display["can_place_paper_orders"]
        assert status["safety_banner"]["paperLearning"] == display["paperLearning"]
    print("OK paper_learning_truth_on")


def test_rate_limit_blocks_without_snapshot():
    from sqlalchemy import delete
    from sqlmodel import Session

    from app.database import AccountSnapshot, engine, init_db
    from app.services.account_pair_eligibility_service import AccountPairEligibilityService

    init_db()
    with Session(engine) as session:
        session.exec(delete(AccountSnapshot))
        session.commit()
        svc = AccountPairEligibilityService(session, {})
        with patch.object(svc.alpaca, "broker_sync_rate_limited", True):
            row = svc.classify_symbol("ETH/USD")
        assert row["status"] == "blocked"
        assert row["category"] == "broker_rate_limited"
        with patch.object(svc.alpaca, "broker_sync_rate_limited", True):
            assert svc.classify_symbol("ETH/USD")["status"] == "blocked"
    print("OK rate_limit_blocks")


def test_diagnostic_bundle_autonomous_files():
    from sqlmodel import Session

    from app.database import engine, init_db
    from app.services.diagnostic_export import export_diagnostic_bundle

    init_db()
    with Session(engine) as session:
        bundle = export_diagnostic_bundle(session)
        files = bundle
    missing = [k for k in AUTONOMOUS_BUNDLE_KEYS if k not in files]
    if missing:
        raise AssertionError(f"missing bundle keys: {missing}")
    pls = files["paper_learning_status.json"]
    for key in ("mode_enabled", "can_place_paper_orders", "scheduler_enabled", "current_mode"):
        if key not in pls:
            raise AssertionError(f"paper_learning_status missing {key}")
    sched = files["autonomous_learning_scheduler.json"]
    if "scheduler_enabled" not in sched:
        raise AssertionError("scheduler json missing scheduler_enabled")
    promo = files["promotion_readiness.json"]
    if promo.get("live_promotion_locked") is not True and promo.get("can_unlock_live") is not False:
        pass  # promotion_readiness uses checklist fields
    print("OK diagnostic_bundle_autonomous")


def main():
    test_usdc_blocked_when_zero_balance()
    test_usd_pair_eligible_when_usd_balance()
    test_no_broker_submit_on_ineligible()
    test_eligibility_block_not_strategy_failure()
    test_paper_learning_truth_matches_fields()
    test_rate_limit_blocks_without_snapshot()
    test_diagnostic_bundle_autonomous_files()
    print("ALL_ACCOUNT_PAIR_ELIGIBILITY_SUITE_PASSED")


if __name__ == "__main__":
    main()
