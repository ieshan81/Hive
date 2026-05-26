#!/usr/bin/env python3
"""Post-NUKE product regression checks — paper learning ready, confidence reset, APIs."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, SQLModel, create_engine, select

from app.database import LessonNode, TradeRecord
from app.services.confidence_engine import ConfidenceEngine
from app.services.config_manager import ConfigManager
from app.services.mission_control_service import mission_control_status
from app.services.nuke_reset_service import execute_nuke_reset
from app.services.paper_learning_blockers import compute_push_pull_blockers
from app.services.paper_learning_start_service import start_fresh_paper_learning
from app.services.universe_service import universe_status
from app.services.activity_feed_service import activity_feed
from app.services.performance_service import equity_curve, performance_summary


def run(name: str, fn):
    fn()
    print(f"OK {name}")


def test_confidence_no_evidence_after_nuke():
    for key in (
        "PAPER_TRADING_PAUSED_BY_ENV",
        "AUTONOMOUS_LEARNING_PAUSED_BY_ENV",
        "SCHEDULER_PAUSED_BY_ENV",
    ):
        os.environ.pop(key, None)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        execute_nuke_reset(session, "test")
        session.commit()
        s = ConfidenceEngine(session).summary()
        assert s["confidence_state"] == "no_evidence"
        assert s["evidence_count"] == 0
        assert s.get("overall") is None
        assert "No evidence" in s.get("overall_label", "")


def test_start_fresh_enables_learning():
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
                "autonomous_paper_learning": {"mode_enabled": False, "scheduler_enabled": False},
                "execution": {"paper_orders_enabled": False, "live_orders_enabled": False},
                "live_trading_enabled": False,
            },
            "test",
            "setup",
        )
        session.commit()
        out = start_fresh_paper_learning(session, "test")
        session.commit()
        assert out["status"] == "ok", out
        cur = cfg_mgr.get_current()
        assert cur["execution"]["paper_orders_enabled"] is True
        assert cur["autonomous_paper_learning"]["mode_enabled"] is True
        assert cur["autonomous_paper_learning"]["scheduler_enabled"] is True
        assert out["live_trading_enabled"] is False


def test_mission_control_no_legacy_blockers():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mc = mission_control_status(session)
        text = " ".join(mc.get("blockers") or [])
        for legacy in ("fast training", "training mode disabled", "fast_training"):
            assert legacy not in text.lower()


def test_mission_control_primary_blocker_when_off():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mc = mission_control_status(session)
        assert mc.get("primary_blocker")
        assert mc.get("primary_blocker_plain")
        assert mc.get("can_place_paper_orders") is False


def test_universe_and_activity_apis():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        u = universe_status(session)
        assert u["status"] == "ok"
        assert "groups" in u
        assert "total_symbols" in u
        a = activity_feed(session)
        assert a["status"] == "ok"
        assert "events" in a


def test_universe_merge_from_radar_when_db_empty():
    from unittest.mock import patch

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    def fake_scan(self, limit=25):
        return {
            "items": [
                {"symbol": "BTC/USD", "broker_supported": True, "price": 1.0, "source": "alpaca"},
                {"symbol": "ETH/USD", "broker_supported": True, "price": 2.0, "source": "alpaca"},
            ]
        }

    with patch("app.services.universe_builder.AttentionRadarService.scan", fake_scan):
        with Session(engine) as session:
            u = universe_status(session)
            assert u["total_symbols"] >= 2


def test_performance_fresh_baseline():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        execute_nuke_reset(session, "test")
        session.commit()
        p = performance_summary(session)
        assert "fresh" in (p.get("fresh_baseline_label") or "").lower() or p.get("post_nuke_only")
        ec = equity_curve(session)
        assert ec["status"] == "ok"


def test_blockers_plain_language():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        b = compute_push_pull_blockers(session)
        for plain in b.get("blockers_plain") or []:
            assert "fast training" not in plain.lower()


def main():
    run("confidence_no_evidence", test_confidence_no_evidence_after_nuke)
    run("start_fresh", test_start_fresh_enables_learning)
    run("mission_control_blockers", test_mission_control_no_legacy_blockers)
    run("primary_blocker", test_mission_control_primary_blocker_when_off)
    run("universe_activity", test_universe_and_activity_apis)
    run("universe_radar_merge", test_universe_merge_from_radar_when_db_empty)
    run("performance_baseline", test_performance_fresh_baseline)
    run("blockers_plain", test_blockers_plain_language)
    print("ALL POST-NUKE PRODUCT CHECKS PASSED")


if __name__ == "__main__":
    main()
