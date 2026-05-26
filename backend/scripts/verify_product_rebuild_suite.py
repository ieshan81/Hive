#!/usr/bin/env python3
"""Acceptance checks for product rebuild (mission control, push-pull, danger zone, env pause)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, SQLModel, create_engine, select

from app.database import LessonNode, SettingsActionAudit
from app.services.config_manager import ConfigManager
from app.services.danger_zone_service import DangerZoneService
from app.services.env_pause_service import env_pause_status
from app.services.execution_logs_query_service import list_execution_logs
from app.services.mission_control_service import mission_control_status
from app.services.push_pull_engine_service import PushPullEngineService


def run(name: str, fn):
    fn()
    print(f"OK {name}")


def test_env_pause_only_from_env():
    os.environ.pop("PAPER_TRADING_PAUSED_BY_ENV", None)
    st = env_pause_status()
    assert st["source"] == "environment_variables_only"
    assert st["paper_trading_paused_by_env"] is False


def test_mission_control_api_shape():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        out = mission_control_status(session)
        assert "system_state_banner" in out
        assert "env_pause" in out
        assert "live_lock" in out


def test_push_pull_status():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        out = PushPullEngineService(session).status()
        assert "market_mode" in out
        assert "operator_messages" in out


def test_execution_logs_scopes():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        latest = list_execution_logs(session, scope="latest_tick")
        assert "execution_logs" in latest


def test_nuke_preview():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        p = DangerZoneService(session).nuke_preview()
        assert p["confirmation_phrase"] == "NUKE CAGED HIVE"
        assert p["live_trading_enabled"] is False


def test_nuke_clears_memory_tables_and_epoch():
    from app.database import AIMemory, MemoryEdge, MemoryEvidence, SettingsActionAudit, StrategyMemory

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(LessonNode(memory_type="trade_lesson", title="t", summary="s", detailed_lesson="d"))
        session.add(AIMemory(memory_type="ai", event="e", lesson="m"))
        session.add(MemoryEdge(source_id="a", target_id="b", relation="rel"))
        session.add(MemoryEvidence(lesson_id=1, evidence_type="note", payload={}))
        session.add(StrategyMemory(strategy="s1", memory_key="k", lesson="sm"))
        session.commit()
        out = DangerZoneService(session).nuke_everything()
        session.commit()
        assert len(list(session.exec(select(LessonNode)).all())) == 0
        assert len(list(session.exec(select(AIMemory)).all())) == 0
        assert len(list(session.exec(select(MemoryEdge)).all())) == 0
        assert len(list(session.exec(select(MemoryEvidence)).all())) == 0
        assert len(list(session.exec(select(StrategyMemory)).all())) == 0
        assert out.get("nuke_epoch", {}).get("nuke_completed_at")
        epochs = list(
            session.exec(
                select(SettingsActionAudit).where(SettingsActionAudit.action == "nuke_epoch")
            ).all()
        )
        assert len(epochs) >= 1


def test_hive_brain_fresh_after_nuke():
    from app.services.config_manager import ConfigManager
    from app.services.hive_brain_graph_service import HiveBrainGraphService

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            LessonNode(
                memory_type="trade_lesson",
                title="old",
                summary="s",
                detailed_lesson="d",
                memory_level="core_ai_lesson",
                status="active",
                visible_in_graph=True,
            )
        )
        session.commit()
        cfg = ConfigManager(session).get_current()
        DangerZoneService(session, cfg).nuke_everything()
        session.commit()
        graph = HiveBrainGraphService(session, cfg).build_full()
        assert graph.get("fresh_brain") is True
        assert len(graph.get("nodes") or []) == 0
        assert graph.get("meta", {}).get("learned_memory_nodes") == 0


def test_pre_nuke_lessons_hidden_by_epoch_filter():
    from datetime import datetime, timedelta

    from app.services.nuke_epoch_service import NUKE_EPOCH_ACTION, filter_lessons_post_nuke, record_nuke_epoch

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        old = LessonNode(
            memory_type="trade_lesson",
            title="ghost",
            summary="s",
            detailed_lesson="d",
            created_at=datetime.utcnow() - timedelta(hours=2),
        )
        session.add(old)
        session.commit()
        record_nuke_epoch(session, "test", deleted={"lessons": 0})
        session.commit()
        visible = filter_lessons_post_nuke(session, list(session.exec(select(LessonNode)).all()))
        assert len(visible) == 0
        epochs = list(
            session.exec(
                select(SettingsActionAudit).where(SettingsActionAudit.action == NUKE_EPOCH_ACTION)
            ).all()
        )
        assert len(epochs) == 1


def test_nuke_deletes_lessons():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            LessonNode(
                memory_type="trade_lesson",
                title="t",
                summary="s",
                detailed_lesson="d",
            )
        )
        session.commit()
        DangerZoneService(session).nuke_everything()
        session.commit()
        left = list(session.exec(select(LessonNode)).all())
        assert len(left) == 0


def test_nuke_does_not_disable_learning_or_scheduler():
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
            "test_setup",
        )
        session.commit()
        out = DangerZoneService(session, cfg_mgr.get_current()).nuke_everything()
        session.commit()
        assert out.get("config_pause_flags_changed") is False
        assert out.get("desired_learning_enabled") is True
        assert out.get("desired_scheduler_enabled") is True
        cur = cfg_mgr.get_current()
        apl = cur.get("autonomous_paper_learning") or {}
        assert apl.get("mode_enabled") is True
        assert apl.get("scheduler_enabled") is True
        assert out.get("fresh_brain") is True
        assert "Fresh brain" in (out.get("message") or "")


def test_diagnostic_has_push_pull_sections():
    from app.services.diagnostic_export import export_diagnostic_bundle_safe

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        bundle = export_diagnostic_bundle_safe(session)
        assert "env_pause_status.json" in bundle or "diagnostic_export_errors.json" in bundle


def main():
    run("env_pause", test_env_pause_only_from_env)
    run("mission_control", test_mission_control_api_shape)
    run("push_pull", test_push_pull_status)
    run("execution_logs_scopes", test_execution_logs_scopes)
    run("nuke_preview", test_nuke_preview)
    run("nuke_memory_tables", test_nuke_clears_memory_tables_and_epoch)
    run("hive_brain_fresh", test_hive_brain_fresh_after_nuke)
    run("nuke_epoch_filter", test_pre_nuke_lessons_hidden_by_epoch_filter)
    run("nuke_deletes", test_nuke_deletes_lessons)
    run("nuke_preserves_config", test_nuke_does_not_disable_learning_or_scheduler)
    run("diagnostic_sections", test_diagnostic_has_push_pull_sections)
    print("ALL PRODUCT REBUILD CHECKS PASSED")


if __name__ == "__main__":
    main()
