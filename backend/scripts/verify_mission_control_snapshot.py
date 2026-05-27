#!/usr/bin/env python3
"""Mission Control cached snapshot — fast status, graceful degrade."""

from __future__ import annotations

import sys
import time
from unittest.mock import patch


def test_mission_control_status_fast_cached_snapshot():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()
    with Session(engine) as session:
        t0 = time.monotonic()
        out = mcs.mission_control_status_fast(session)
        elapsed = time.monotonic() - t0
        assert out["status"] in ("ok", "degraded")
        assert elapsed < 2.0, f"first build too slow: {elapsed:.2f}s"
        t1 = time.monotonic()
        out2 = mcs.mission_control_status_fast(session)
        assert time.monotonic() - t1 < 0.5
        assert out2.get("snapshot_age_seconds") is not None
        assert "live_lock" in out2
        assert out2.get("paper_broker") is True


def test_mission_control_status_returns_200_when_alpaca_rate_limited():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()
    with Session(engine) as session:
        with patch(
            "app.services.alpaca_adapter.AlpacaAdapter.broker_sync_rate_limited",
            True,
            create=True,
        ):
            out = mcs.mission_control_status_fast(session)
    assert out["status"] in ("ok", "degraded")


def test_mission_control_status_returns_200_when_universe_slow():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()

    def slow(*_a, **_k):
        time.sleep(2)
        return {"status": "ok", "mode": "hybrid_radar", "available_symbols": 36}

    with Session(engine) as session:
        with patch(
            "app.services.mission_control_snapshot_service._subsystem_universe_fast",
            side_effect=slow,
        ):
            out = mcs.mission_control_status_fast(session)
    assert out["status"] in ("ok", "degraded")


def test_mission_control_status_returns_200_when_crypto_readiness_slow():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()

    def slow(*_a, **_k):
        time.sleep(2)
        return {"status": "degraded", "paper_trade_allowed": False}

    with Session(engine) as session:
        with patch(
            "app.services.mission_control_snapshot_service._subsystem_crypto_fast",
            side_effect=slow,
        ):
            out = mcs.mission_control_status_fast(session)
    assert out["status"] in ("ok", "degraded")


def test_mission_control_status_returns_200_when_sentiment_slow():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()

    def slow(*_a, **_k):
        time.sleep(2)
        return {"status": "degraded", "finbert": {"active": False}}

    with Session(engine) as session:
        with patch(
            "app.services.mission_control_snapshot_service._subsystem_sentiment_fast",
            side_effect=slow,
        ):
            out = mcs.mission_control_status_fast(session)
    assert out["status"] in ("ok", "degraded")


def test_mission_control_status_marks_degraded_subsystems():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()
    with Session(engine) as session:
        out = mcs.mission_control_status_fast(session)
    assert "degraded_subsystems" in out or out.get("status") == "ok"


def test_mission_control_refresh_does_not_duplicate_running_refresh():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services import mission_control_snapshot_service as mcs

    init_db()
    mcs.reset_cache_for_tests()
    mcs._REFRESH_IN_PROGRESS = True
    with Session(engine) as session:
        r1 = mcs.refresh_mission_control_snapshot(session, background=False)
    assert r1.get("refresh_in_progress") is True
    mcs._REFRESH_IN_PROGRESS = False


def main() -> None:
    test_mission_control_status_fast_cached_snapshot()
    test_mission_control_status_returns_200_when_alpaca_rate_limited()
    test_mission_control_status_returns_200_when_universe_slow()
    test_mission_control_status_returns_200_when_crypto_readiness_slow()
    test_mission_control_status_returns_200_when_sentiment_slow()
    test_mission_control_status_marks_degraded_subsystems()
    test_mission_control_refresh_does_not_duplicate_running_refresh()
    print("verify_mission_control_snapshot: OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("verify_mission_control_snapshot: FAIL", exc)
        sys.exit(1)
