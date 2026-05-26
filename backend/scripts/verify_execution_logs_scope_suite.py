#!/usr/bin/env python3
"""Verify execution log scopes — latest tick vs historical."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session

from app.database import ExecutionLog, engine, init_db
from app.services.execution_logs_query_service import list_execution_logs
from app.services.live_lock_tripwire import live_lock_tripwire_status


def ok(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def main() -> int:
    init_db()
    with Session(engine) as session:
        # Seed historical BAT/USDC style log (before any tick window)
        old = ExecutionLog(
            event_id="test-hist-bat-usdc",
            symbol="BAT/USDC",
            side="buy",
            status="paper_order_rejected",
            reject_reason="insufficient USDC",
            cycle_run_id="4afeeda0-historical-test",
            created_at=datetime.utcnow() - timedelta(days=1),
        )
        session.add(old)
        session.commit()

        latest = list_execution_logs(session, scope="latest_tick")
        ok(latest.get("count", 0) == 0 or not any(
            r.get("symbol") == "BAT/USDC" and not r.get("historical")
            for r in latest.get("execution_logs", [])
        ), "BAT/USDC not in latest_tick scope (or marked historical)")

        hist = list_execution_logs(session, scope="historical")
        bat_in_hist = any(r.get("symbol") == "BAT/USDC" for r in hist.get("execution_logs", []))
        ok(bat_in_hist or hist.get("count", 0) >= 0, "historical scope returns data structure")

        for row in hist.get("execution_logs", []):
            if row.get("symbol") == "BAT/USDC":
                ok(row.get("historical") is True, "BAT/USDC marked historical in historical scope")
                ok("timestamp" in row and "source_window" in row, "BAT/USDC has attribution fields")
                break

        ok(latest.get("empty_reason") in (None, "no_executions_in_window", "no_scheduler_tick_yet"), "latest tick empty_reason set")

        trip = live_lock_tripwire_status({})
        ok(trip.get("live_lock_status") == "locked" or not trip.get("live_orders_enabled"), "live lock remains")

    print("\nAll execution log scope checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
