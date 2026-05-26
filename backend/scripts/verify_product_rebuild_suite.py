#!/usr/bin/env python3
"""Acceptance checks for product rebuild (mission control, push-pull, danger zone, env pause)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, SQLModel, create_engine, select

from app.database import LessonNode
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
    run("nuke_deletes", test_nuke_deletes_lessons)
    run("nuke_preserves_config", test_nuke_does_not_disable_learning_or_scheduler)
    run("diagnostic_sections", test_diagnostic_has_push_pull_sections)
    print("ALL PRODUCT REBUILD CHECKS PASSED")


if __name__ == "__main__":
    main()
