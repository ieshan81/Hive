"""/api/execution/logs default returns recent logs across all cycles (not 0)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import ExecutionLog
from app.services.execution_logs_query_service import list_execution_logs


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed(s, n=3):
    for i in range(n):
        s.add(ExecutionLog(event_id=f"e{i}", cycle_run_id="c1", symbol="SOL/USD", side="buy",
                           status="paper_order_filled", created_at=datetime(2026, 5, 30, 10, i, 0)))
    s.commit()


def test_scope_all_returns_logs() -> None:
    s = _mem()
    _seed(s, 3)
    res = list_execution_logs(s, scope="all", limit=200)
    assert res["scope"] == "all" and res["count"] >= 3, res
    s.close()
    print("exec-logs: scope=all returns recent logs across cycles — PASS")


def test_latest_tick_empty_without_tick() -> None:
    s = _mem()
    _seed(s, 2)
    res = list_execution_logs(s, scope="latest_tick", limit=200)
    assert res["count"] == 0, res  # the OLD default trap: no tick -> 0 despite logs existing
    s.close()
    print("exec-logs: latest_tick empty without a tick (reproduces the old default) — PASS")


def test_route_default_and_diagnostics() -> None:
    from app.routers.api import get_execution_logs

    s = _mem()
    _seed(s, 2)
    # Default: no cycle_run_id, no scope -> all-recent + diagnostics.
    res = get_execution_logs(cycle_run_id=None, scope=None, limit=200, session=s)
    assert res["filter_scope"] == "all" and res["returned_count"] >= 2, res
    assert res["total_execution_log_count"] >= 2 and "latest_cycle_run_id" in res, res
    # cycle_run_id=latest still routes to the single-cycle path.
    res2 = get_execution_logs(cycle_run_id="latest", scope=None, limit=200, session=s)
    assert res2["filter_scope"] == "cycle", res2
    s.close()
    print("exec-logs: route default -> all-recent + diagnostics; cycle_run_id=latest -> cycle — PASS")


if __name__ == "__main__":
    test_scope_all_returns_logs()
    test_latest_tick_empty_without_tick()
    test_route_default_and_diagnostics()
    print("ALL PASS: verify_execution_logs_default_scope")
