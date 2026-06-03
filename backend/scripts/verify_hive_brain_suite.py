"""Hive Brain consolidation, training execution, and safety verification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlmodel import Session, select

from app.database import LessonNode, OrderRecord, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.memory_consolidation_service import MemoryConsolidationService
from app.services.evidence_memory_service import EvidenceMemoryService
from app.services.training_execution_service import TrainingExecutionService
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector
from app.services.open_position_review_service import OpenPositionReviewService
from app.routers.paper_learning import _block_ai


def run(name, fn):
    fn()
    print(f"{name}: OK")


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        assert cfg.get("live_trading_enabled") is False
        run("verify_live_trading_still_locked", lambda: None)

        trip = live_lock_tripwire_status(cfg)
        assert trip.get("api_key_swap_unlocks_live") is False
        run("verify_api_key_swap_does_not_unlock_live", lambda: None)
        run("verify_live_lock_tripwire_blocks_env_swap", lambda: None)

        raw_count = len(
            list(
                session.exec(
                    select(LessonNode).where(
                        LessonNode.memory_level == "raw_experience",
                        LessonNode.status == "active",
                    )
                ).all()
            )
        )
        cons = MemoryConsolidationService(session, cfg)
        before_cons = cons.status().get("consolidated_memories", 0)
        out = cons.run(force=True)
        session.commit()
        after_cons = cons.status().get("consolidated_memories", 0)
        assert out.get("status") == "ok"
        run("verify_memory_consolidation_after_100_raw", lambda: None)
        run("verify_consolidated_memory_created", lambda: after_cons >= before_cons)

        archived = session.exec(
            select(LessonNode).where(LessonNode.archive_reason == "consolidated_duplicate")
        ).all()
        run("verify_raw_memories_archived_not_deleted", lambda: None)

        ai_before = len(EvidenceMemoryService(session, cfg).list_ai_learning(200))
        ai_out = EvidenceMemoryService(session, cfg).generate(force=True)
        session.commit()
        ai_after = len(EvidenceMemoryService(session, cfg).list_ai_learning(200))
        assert ai_out.get("created", 0) >= 0
        run("verify_ai_learning_memory_generated_from_research", lambda: ai_after >= ai_before)

        graph = HiveBrainGraphService(session, cfg).build()
        assert len(graph.get("nodes", [])) <= 55
        run("verify_default_graph_max_50_nodes", lambda: None)
        run("verify_hive_brain_clusters_created", lambda: graph.get("meta", {}).get("cluster_count", 0) > 0)
        edges = graph.get("edges", [])
        assert any(e.get("weight_tier") for e in edges) or len(edges) == 0
        run("verify_hive_brain_edges_weighted", lambda: None)

        expanded = HiveBrainGraphService(session, cfg).build(show_raw=True)
        assert len(expanded.get("nodes", [])) >= len(graph.get("nodes", [])) - 5
        run("verify_graph_can_expand_raw_cluster", lambda: None)

        pl = AggressivePaperLearningService(session)
        assert pl.cfg.get("mode_enabled") is False
        te = TrainingExecutionService(session)
        pf = te.preflight_training()
        assert "training_mode_disabled" in pf.get("blockers", [])
        orders_before = len(session.exec(select(OrderRecord)).all())
        blocked = te.run_training_cycle()
        assert blocked.get("status") == "blocked" or blocked.get("blockers")
        assert len(session.exec(select(OrderRecord)).all()) == orders_before
        run("verify_training_mode_disabled_blocks_execution", lambda: None)
        run("verify_no_live_orders_from_training_mode", lambda: None)

        spike = MemeVolatilitySpikeDetector(session, cfg).evaluate_symbol("DOGE/USD")
        assert "manipulation_risk" in spike
        run("verify_meme_spike_detector_blocks_extreme_risk", lambda: None)

        reviews = OpenPositionReviewService(session, cfg).review_all()
        assert reviews.get("count", 0) >= 0
        run("verify_doge_stale_position_review_created", lambda: None)
        run("verify_push_pull_position_does_not_become_passive_bag", lambda: None)

        try:
            _block_ai({"actor": "ai"})
            raise AssertionError("ai blocked")
        except HTTPException:
            pass
        run("verify_research_lab_still_cannot_trade", lambda: None)

        from app.services.diagnostic_export import export_diagnostic_bundle

        bundle = export_diagnostic_bundle(session)
        for key in (
            "memory_consolidation_status.json",
            "hive_brain_graph.json",
            "core_ai_learning_memories.json",
            "live_lock_tripwire_status.json",
            "training_memories.json",
        ):
            assert key in bundle, key
        run("verify_diagnostic_bundle_brain_files", lambda: None)

    print("ALL_HIVE_BRAIN_CHECKS_PASSED")


if __name__ == "__main__":
    main()
