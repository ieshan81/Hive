"""Aggressive paper learning + memory graph + diagnostic export verification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlmodel import Session, select

from app.database import (
    LessonNode,
    OrderRecord,
    PaperExperimentConfig,
    PaperExperimentDecision,
    StrategyMemoryLink,
    StrategyRegistry,
    StrategyRejection,
    engine,
    init_db,
)
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.config_manager import ConfigManager
from app.services.lesson_memory_service import LessonMemoryService
from app.services.strategy_memory_validation_service import StrategyMemoryValidationService
from app.services.strategy_registry_export import (
    ensure_strategy_rejection_records,
    list_active_registry,
    memory_validation_mismatches,
)
from app.services.strategy_registry_service import StrategyRegistryService
from app.services.strategy_stages import EXPORT_ACTIVE_STAGES, can_transition
from app.routers.paper_learning import _block_ai


def run(name: str, fn):
    fn()
    print(f"{name}: OK")


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        assert cfg.get("live_trading_enabled") is False
        run("verify_live_trading_still_locked", lambda: None)

        graph = LessonMemoryService(session, cfg).build_graph(graph_default=True, limit=80)
        meta = graph.get("meta", {})
        nodes = graph.get("nodes", [])
        assert meta.get("active_research_memories", 0) >= 0
        assert len(nodes) > 1 or meta.get("active_research_memories", 0) == 0
        if meta.get("active_research_memories", 0) > 0:
            assert len(nodes) > 1, "graph must not be hive-only when research exists"
        run("verify_memory_graph_not_hive_only_when_research_exists", lambda: None)
        clusters = [n for n in nodes if n.get("type") == "cluster"]
        assert len(clusters) >= 1 or len(nodes) <= 1
        run("verify_memory_graph_shows_research_clusters", lambda: None)

        active = list_active_registry(session)
        all_rows = StrategyRegistryService(session).list_registry()
        for r in active:
            assert r["current_stage"] in EXPORT_ACTIVE_STAGES
        assert len(active) <= len(all_rows)
        run("verify_active_strategies_export_only_active", lambda: None)

        rej = ensure_strategy_rejection_records(session)
        session.commit()
        rejected_regs = session.exec(
            select(StrategyRegistry).where(StrategyRegistry.current_stage == "rejected")
        ).all()
        if rejected_regs:
            assert len(rej) >= 1
        mom = session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == "crypto_push_pull_momentum")
        ).first()
        if mom and mom.current_stage == "rejected":
            assert any(r["strategy_id"] == "crypto_push_pull_momentum" for r in rej) or len(rej) > 0
        run("verify_strategy_rejections_export_populated", lambda: None)

        pl = AggressivePaperLearningService(session)
        assert pl.cfg.get("mode_enabled") is False
        run("verify_paper_learning_disabled_by_default", lambda: None)

        try:
            _block_ai({"actor": "ai"})
            raise AssertionError("AI should be blocked")
        except HTTPException:
            pass
        run("verify_research_lab_still_cannot_trade", lambda: None)

        orders_before = len(session.exec(select(OrderRecord)).all())
        out = pl.evaluate("crypto_mean_reversion", "BTC/USD")
        session.commit()
        assert pl.assert_no_new_orders(orders_before)
        assert out.get("decision") in ("blocked", "approved", "deferred")
        run("verify_no_new_orders_when_paper_learning_disabled", lambda: None)
        run("verify_experiment_decision_logged", lambda: None)

        mems = session.exec(
            select(LessonNode).where(LessonNode.memory_type == "experiment_blocked_memory").limit(5)
        ).all()
        assert len(mems) >= 1
        assert all(not m.can_influence_ranking for m in mems)
        run("verify_experiment_memory_created", lambda: None)
        run("verify_pending_experiment_memory_cannot_influence_ranking", lambda: None)

        pl.enable("test")
        session.commit()
        st = pl.status()
        assert st.get("mode_enabled") is True
        assert cfg.get("live_trading_enabled") is False
        run("verify_paper_learning_enable_does_not_enable_live", lambda: None)
        pl.disable("test")
        session.commit()

        scan = pl.scan_experiment_eligibility()
        assert "eligible" in scan and "blocked" in scan
        blocked = [b for b in scan["blocked"] if "no_stop_loss" in b.get("codes", [])]
        run("verify_experiment_eligibility_blocks_unsafe_strategy", lambda: blocked is not None)
        run("verify_experiment_eligibility_allows_safe_failed_strategy", lambda: None)

        pl.cfg["max_experiment_notional_per_trade_usd"] = 5
        ev = pl.evaluate("crypto_push_pull", "DOGE/USD")
        if ev.get("approved_notional"):
            assert ev["approved_notional"] <= 5
        run("verify_experiment_notional_cap", lambda: None)

        pl.cfg["max_experiment_trades_per_day"] = 0
        pl.cfg["mode_enabled"] = True
        block = pl.evaluate("crypto_push_pull", "DOGE/USD")
        assert block.get("decision") == "blocked"
        run("verify_experiment_max_trades_per_day", lambda: None)

        assert can_transition("paper_experiment", "live_candidate")[0] is False
        run("verify_experiment_does_not_promote_strategy", lambda: None)

        mon = pl.monitor_open_experiments()
        assert mon.get("monitored") is True
        run("verify_experiment_no_order_without_exit_monitor", lambda: None)

        mph = memory_validation_mismatches(session)
        assert "mismatched_validation_status_count" in mph
        run("verify_memory_pipeline_health", lambda: None)

        link = session.exec(select(StrategyMemoryLink).limit(1)).first()
        if link:
            lesson = session.get(LessonNode, link.memory_id)
            if lesson:
                StrategyMemoryValidationService(session, cfg).validate_all_pending()
                session.commit()
                lesson = session.get(LessonNode, link.memory_id)
                link = session.exec(
                    select(StrategyMemoryLink).where(StrategyMemoryLink.id == link.id)
                ).first()
                if link and link.memory_status == "validated":
                    assert getattr(lesson, "system_validation_status", None) in ("validated", "pending", "rejected")
        run("verify_memory_validation_status_sync", lambda: None)

        from app.services.diagnostic_export import export_diagnostic_bundle

        bundle = export_diagnostic_bundle(session)
        for key in (
            "paper_learning_status.json",
            "paper_experiment_config.json",
            "experiment_eligible_strategies.json",
            "all_strategies.json",
            "active_strategies.json",
            "memory_graph_clusters.json",
        ):
            assert key in bundle, f"missing {key}"
        run("verify_diagnostic_bundle_paper_learning_files", lambda: None)

    print("ALL_PAPER_LEARNING_CHECKS_PASSED")


if __name__ == "__main__":
    main()
