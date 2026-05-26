#!/usr/bin/env python3
"""P0 NUKE reset engine verification."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, SQLModel, create_engine, select

from app.database import (
    AIMemory,
    BrokerError,
    ExecutionLog,
    LessonNode,
    MemoryEdge,
    SettingsActionAudit,
)
from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
from app.services.config_manager import ConfigManager
from app.services.danger_zone_service import DangerZoneService
from app.services.database_bootstrap_service import list_missing_tables, repair_database_bootstrap
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.nuke_reset_service import RESET_LOCK_ACTION, execute_nuke_reset, is_reset_in_progress


def run(name: str, fn):
    fn()
    print(f"OK {name}")


def test_nuke_clears_all_memory_tables():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(LessonNode(memory_type="t", title="a", summary="s", detailed_lesson="d"))
        session.add(AIMemory(memory_type="ai", event="e", lesson="m"))
        session.add(MemoryEdge(source_id="a", target_id="b", relation="r"))
        session.commit()
        out = execute_nuke_reset(session, "test")
        session.commit()
        assert out["status"] == "ok"
        assert out.get("reset_epoch_id")
        assert len(list(session.exec(select(LessonNode)).all())) == 0
        assert len(list(session.exec(select(AIMemory)).all())) == 0
        assert len(list(session.exec(select(MemoryEdge)).all())) == 0
        assert len(list(session.exec(select(ExecutionLog)).all())) == 0
        assert len(list(session.exec(select(BrokerError)).all())) == 0
        assert out["post_nuke_counts"].get("lesson_nodes") == 0


def test_hive_brain_empty_after_nuke():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            LessonNode(
                memory_type="trade_lesson",
                title="x",
                summary="s",
                detailed_lesson="d",
                memory_level="core_ai_lesson",
                status="active",
                visible_in_graph=True,
            )
        )
        session.commit()
        cfg = ConfigManager(session).get_current()
        execute_nuke_reset(session, "test")
        session.commit()
        g = HiveBrainGraphService(session, cfg).build_full()
        assert g.get("fresh_brain") is True
        assert g.get("learned_memory_nodes") == 0
        assert len(g.get("nodes") or []) == 0
        assert "Fresh brain" in (g.get("message") or "")


def test_nuke_preserves_learning_flags():
    for key in (
        "PAPER_TRADING_PAUSED_BY_ENV",
        "AUTONOMOUS_LEARNING_PAUSED_BY_ENV",
        "SCHEDULER_PAUSED_BY_ENV",
    ):
        os.environ.pop(key, None)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        cfg_mgr = ConfigManager(session)
        cfg_mgr._activate(
            {
                "autonomous_paper_learning": {"mode_enabled": True, "scheduler_enabled": True},
                "live_trading_enabled": False,
                "execution": {"live_orders_enabled": False, "paper_orders_enabled": True},
            },
            "test",
            "setup",
        )
        session.commit()
        out = DangerZoneService(session, cfg_mgr.get_current()).nuke_everything()
        session.commit()
        cur = cfg_mgr.get_current()
        apl = cur.get("autonomous_paper_learning") or {}
        assert apl.get("mode_enabled") is True
        assert apl.get("scheduler_enabled") is True
        assert out.get("config_pause_flags_changed") is False
        assert out.get("live_lock_status") == "locked" or out.get("live_trading_enabled") is False


def test_tick_skipped_during_reset_lock():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        from datetime import datetime

        from app.database import SettingsActionAudit

        session.add(
            SettingsActionAudit(
                action=RESET_LOCK_ACTION,
                actor="test",
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json={"started_at": datetime.utcnow().isoformat() + "Z"},
            )
        )
        session.commit()
        assert is_reset_in_progress(session)
        tick = AutonomousPaperScheduler(session, cfg).tick()
        assert tick.get("reason") == "reset_in_progress"


def test_fresh_db_bootstrap():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        out = repair_database_bootstrap(session)
        assert out["status"] == "ok"
        assert out["database_bootstrap_status"]["config_current"] == "present"
        assert list_missing_tables() == []


def test_ai_manager_empty_after_nuke():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(LessonNode(memory_type="t", title="a", summary="s", detailed_lesson="d"))
        session.commit()
        cfg = ConfigManager(session).get_current()
        execute_nuke_reset(session, "test")
        session.commit()
        from app.services.ai_manager_service import AIManagerService

        mem = AIManagerService(session, cfg).memories()
        les = AIManagerService(session, cfg).lessons()
        assert mem["count"] == 0
        assert les["count"] == 0


def main():
    run("nuke_clears_tables", test_nuke_clears_all_memory_tables)
    run("hive_brain_empty", test_hive_brain_empty_after_nuke)
    run("preserves_learning", test_nuke_preserves_learning_flags)
    run("tick_reset_lock", test_tick_skipped_during_reset_lock)
    run("fresh_db_bootstrap", test_fresh_db_bootstrap)
    run("ai_manager_empty", test_ai_manager_empty_after_nuke)
    print("ALL NUKE RESET CHECKS PASSED")


if __name__ == "__main__":
    main()
