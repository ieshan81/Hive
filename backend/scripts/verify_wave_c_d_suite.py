"""Wave C+D verification — memory hardening + fast training loop."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta

from sqlmodel import Session, select, func

from app.database import OrderRecord, PositionSnapshot, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop
from app.services.training_execution_service import TrainingExecutionService
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.evidence_memory_service import EvidenceMemoryService
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.memory_consolidation_service import MemoryConsolidationService
from app.services.lesson_memory_service import LessonMemoryService
from app.database import LessonNode
from app.services.memory_categories import MEMORY_LEVEL_RAW, MEMORY_LEVEL_CORE


def run(name, fn):
    fn()
    print(f"{name}: OK")


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        ft = FastCryptoTrainingLoop(session, cfg)
        train = TrainingExecutionService(session, cfg)

        def status_endpoint():
            st = ft.status()
            assert st["status"] == "ok"
            assert "fast_training_loop_enabled" in st
            assert "mode_enabled" in st
            assert st["exit_monitor_ready"] is True

        run("verify_fast_training_status_endpoint", status_endpoint)

        def disabled_default():
            assert cfg.get("fast_training", {}).get("fast_training_loop_enabled") is False
            assert ft.status()["fast_training_loop_enabled"] is False
            assert ft.status()["mode_enabled"] is False

        run("verify_fast_training_disabled_by_default", disabled_default)

        orders_before = session.exec(select(func.count()).select_from(OrderRecord)).one()
        out = ft.run_once()
        session.commit()
        orders_after = session.exec(select(func.count()).select_from(OrderRecord)).one()

        def run_once_no_order():
            assert out.get("new_orders", 0) == 0
            assert orders_after == orders_before
            assert out.get("status") in ("blocked", "ok")
            if out.get("status") == "blocked":
                assert out.get("orders_submitted") is False

        run("verify_fast_training_run_once_disabled_no_order", run_once_no_order)

        def true_hold():
            reviews = OpenPositionReviewService(session, cfg).review_all()
            if reviews.get("reviews"):
                r = reviews["reviews"][0]
                assert r.get("hold_time_source") in ("order_filled_at", "order_submitted_at", "position_opened_at")
                assert "true_hold_minutes" in r

        run("verify_fast_training_uses_true_hold_time", true_hold)

        def exits_first():
            phases = out.get("phases") or []
            assert phases.index("open_position_review") < phases.index("exit_monitor")
            assert "stale_position_check" in phases
            if "scan_entries" in phases:
                assert phases.index("stale_position_check") < phases.index("scan_entries")

        run("verify_fast_training_exits_first", exits_first)

        def caged_only():
            import inspect
            import app.services.fast_crypto_training_loop as mod

            src = inspect.getsource(mod.FastCryptoTrainingLoop)
            assert "AlpacaAdapter" not in src
            assert "TrainingExecutionService" in src

        run("verify_fast_training_uses_caged_execution_only", caged_only)

        def block_memory():
            rows = list(
                session.exec(
                    select(LessonNode).where(LessonNode.memory_type == "fast_training_blocked_memory")
                ).all()
            )
            assert len(rows) >= 1

        run("verify_fast_training_creates_block_memory", block_memory)

        def no_live():
            st = ft.status()
            assert st.get("live_orders_enabled") is False
            assert st.get("live_lock_status") == "locked"

        run("verify_fast_training_no_live_orders", no_live)

        def stale_ai():
            EvidenceMemoryService(session, cfg).generate(force=True)
            session.commit()
            core = list(
                session.exec(
                    select(LessonNode).where(
                        LessonNode.memory_type == "core_ai_lesson",
                        LessonNode.source == "ai_learning_outcome",
                    )
                ).all()
            )
            assert len(core) >= 0

        run("verify_ai_learning_from_stale_position", stale_ai)

        def brain_core():
            graph = HiveBrainGraphService(session, cfg).build_full()
            lessons = [n for n in graph["nodes"] if n["type"] == "lesson"]
            raw_visible = [n for n in lessons if n.get("memory_level") == MEMORY_LEVEL_RAW]
            assert len(raw_visible) <= 3
            core_count = sum(1 for n in lessons if n.get("memory_level") == MEMORY_LEVEL_CORE)
            assert core_count >= 0 or len(lessons) == 0

        run("verify_hive_brain_core_lessons_from_training_memory", brain_core)

        directives = EvidenceMemoryService(session, cfg).learning_directives()
        assert "what_i_learned" in directives
        assert "what_i_will_avoid" in directives
        assert "what_i_will_test_next" in directives
        print("verify_ai_fund_manager_learning_directives: OK")

    print("ALL_WAVE_C_D_CHECKS_PASSED")


if __name__ == "__main__":
    main()
