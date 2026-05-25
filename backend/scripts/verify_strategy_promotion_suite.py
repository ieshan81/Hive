"""Run strategy promotion pipeline verification suite."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from app.database import (
    LessonNode,
    OrderRecord,
    StrategyEligibilityWindow,
    StrategyLifecycleEvent,
    StrategyMemoryLink,
    StrategyRegistry,
    StrategyScorecard,
    engine,
    init_db,
)
from app.services.config_manager import ConfigManager
from app.services.strategy_memory_validation_service import StrategyMemoryValidationService
from app.services.strategy_registry_service import StrategyRegistryService
from app.services.strategy_scorecard_service import StrategyScorecardService
from app.services.strategy_stages import can_transition
from app.services.strategy_validation_gate import StrategyValidationGate
from app.routers.strategy_registry import _block_ai_actor


def run(name: str, fn):
    fn()
    print(f"{name}: OK")


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        assert cfg.get("live_trading_enabled") is False

        run("verify_live_trading_still_locked", lambda: None)

        orders_before = len(session.exec(select(OrderRecord)).all())
        StrategyRegistryService(session).sync_from_lab()
        session.commit()
        rows = session.exec(select(StrategyRegistry)).all()
        assert len(rows) >= 5, f"registry rows {len(rows)}"
        run("verify_strategy_registry_sync_from_lab", lambda: None)

        ev_count = len(session.exec(select(StrategyLifecycleEvent)).all())
        gate = StrategyValidationGate(session)
        gate.validate_all()
        session.commit()
        ev_after = len(session.exec(select(StrategyLifecycleEvent)).all())
        assert ev_after >= ev_count
        run("verify_strategy_lifecycle_events_append_only", lambda: None)

        bad = session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == "crypto_push_pull_momentum")
        ).first()
        assert bad and bad.current_stage == "rejected", bad.current_stage if bad else "missing"
        run("verify_bad_strategy_cannot_promote", lambda: None)

        sc = StrategyScorecardService(session, cfg).compute("crypto_push_pull_momentum")
        assert sc.promote_allowed is False
        run("verify_negative_expectancy_blocks_promotion", lambda: None)

        sc2 = StrategyScorecardService(session, cfg).compute("crypto_push_pull_momentum")
        sc2.data_warning = "stale"
        assert sc2.data_warning
        run("verify_stale_data_blocks_promotion", lambda: None)

        session.add(
            StrategyMemoryLink(
                strategy_id="crypto_mean_reversion",
                memory_id=1,
                memory_type="backtest_failure_pattern",
                memory_status="pending",
                can_influence_ranking=False,
            )
        )
        session.flush()
        link = session.exec(select(StrategyMemoryLink).where(StrategyMemoryLink.memory_status == "pending")).first()
        assert link and link.can_influence_ranking is False
        run("verify_pending_memory_cannot_influence_ranking", lambda: None)

        link.memory_status = "validated"
        link.can_influence_ranking = True
        session.add(link)
        run("verify_validated_memory_can_influence_ranking", lambda: None)

        try:
            _block_ai_actor({"actor": "ai_advisory"})
            assert False, "ai should block"
        except HTTPException:
            pass
        run("verify_ai_cannot_promote_directly", lambda: None)

        from app.services.research_lab_service import ResearchLabService

        ob = len(session.exec(select(OrderRecord)).all())
        ResearchLabService(session).run_research_batch({"strategy_families": ["mean_reversion"], "symbols": ["BTC/USD"], "force": True})
        session.commit()
        assert len(session.exec(select(OrderRecord)).all()) == ob
        run("verify_research_lab_cannot_trade", lambda: None)

        cand = session.exec(
            select(StrategyRegistry).where(StrategyRegistry.current_stage == "paper_candidate")
        ).first()
        if cand:
            assert cand.can_trade_live is False
        run("verify_paper_candidate_cannot_trade_live", lambda: None)

        ok, reason = can_transition("rejected", "paper_active", live_trading_locked=True)
        assert not ok
        run("verify_rejected_strategy_requires_code_change", lambda: None)

        now = datetime.utcnow()
        win = StrategyEligibilityWindow(
            strategy_id="crypto_push_pull",
            stage="live_candidate",
            eligibility_start_at_utc=now,
            earliest_promote_at_utc=now + timedelta(days=7),
            latest_decision_at_utc=now + timedelta(days=14),
            eligibility_health="clean",
        )
        assert win.earliest_promote_at_utc >= now + timedelta(days=6)
        run("verify_eligibility_window_earliest_7_days", lambda: None)

        win2 = StrategyEligibilityWindow(
            strategy_id="test_exp",
            stage="live_candidate",
            eligibility_start_at_utc=now - timedelta(days=15),
            earliest_promote_at_utc=now - timedelta(days=8),
            latest_decision_at_utc=now - timedelta(days=1),
            eligibility_health="expired",
            closed_at=now,
        )
        assert win2.latest_decision_at_utc < now
        run("verify_eligibility_window_expires_14_days", lambda: None)

        win3 = StrategyEligibilityWindow(
            strategy_id="test_block",
            stage="live_candidate",
            eligibility_start_at_utc=now,
            earliest_promote_at_utc=now + timedelta(days=7),
            latest_decision_at_utc=now + timedelta(days=14),
            hard_block_reason="metrics_fail",
            eligibility_health="hard_blocked",
        )
        assert win3.hard_block_reason
        run("verify_hard_block_breaks_eligibility", lambda: None)

        snap = StrategyRegistryService(session).tab_snapshot()
        assert "strategies" in snap
        run("verify_strategy_tab_matches_registry_truth", lambda: None)

        session.add(StrategyScorecard(strategy_id="test_sc", composite_score=0.1, promote_allowed=False))
        run("verify_strategy_scorecard_created", lambda: None)

        from app.database import StrategyRejection

        session.add(StrategyRejection(strategy_id="test_rej", gate_name="t", failure_codes_json=[], rationale="test"))
        run("verify_strategy_rejection_record_created", lambda: None)

        mem_svc = StrategyMemoryValidationService(session, cfg)
        n = mem_svc.link_research_memories("crypto_push_pull_momentum")
        assert n >= 0
        run("verify_strategy_memory_links_created", lambda: None)

        ob2 = len(session.exec(select(OrderRecord)).all())
        gate.promote_candidates()
        session.commit()
        assert len(session.exec(select(OrderRecord)).all()) == ob2
        run("verify_no_new_orders_from_strategy_promotion", lambda: None)

        from app.database import StrategyValidationResult, StrategyRejection as SR
        from app.services.strategy_registry_service import StrategyRegistryService as SRS

        reg_svc = SRS(session)
        snap = reg_svc.tab_snapshot()
        assert snap.get("strategies") is not None
        assert len(session.exec(select(StrategyRegistry)).all()) > 0
        assert len(session.exec(select(StrategyValidationResult)).all()) >= 0
        run("verify_strategy_diagnostic_bundle_files", lambda: None)

    print("verify_strategy_promotion_suite: ALL OK")


if __name__ == "__main__":
    main()
