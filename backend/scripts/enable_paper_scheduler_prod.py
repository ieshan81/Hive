"""Post-deploy safe enable — scheduler/enable + supervised burst (NOT start-fresh).

Usage:
  set OPERATOR_TOKEN=<matches Railway OPERATOR_SECRET>
  set HIVE_BACKEND=https://hive-production-7343.up.railway.app
  python backend/scripts/enable_paper_scheduler_prod.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _post(path: str, body: dict | None = None) -> dict:
    backend = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app").rstrip("/")
    token = os.environ.get("OPERATOR_TOKEN", "").strip()
    if not token:
        print("OPERATOR_TOKEN required (must match backend OPERATOR_SECRET)")
        sys.exit(2)
    req = urllib.request.Request(
        f"{backend}{path}",
        data=json.dumps(body or {"operator": "operator"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Operator-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict:
    backend = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app").rstrip("/")
    with urllib.request.urlopen(f"{backend}{path}", timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    run_before = _get("/api/paper-validation/productivity").get("validation_run_id")
    print(f"validation_run_id before: {run_before}")

    enable = _post("/api/autonomous-paper-learning/scheduler/enable")
    print("scheduler/enable:", enable.get("scheduler_enabled"), enable.get("status"))

    burst = _post("/api/autonomous-paper-learning/supervised-burst", {"max_ticks": 2, "operator": "operator"})
    print("supervised-burst ticks_run:", burst.get("ticks_run"), "stopped:", burst.get("stopped_reason"))

    tiles = _get("/api/mission-control/tiles")
    pe = tiles.get("paper_execution") or {}
    print("scheduler_enabled:", pe.get("scheduler_enabled"), "blockers:", pe.get("blocker_codes"))

    run_after = _get("/api/paper-validation/productivity").get("validation_run_id")
    print(f"validation_run_id after: {run_after}")
    if run_before and run_after and run_before != run_after:
        print("ERROR: validation_run_id changed")
        sys.exit(1)

    sched = _get("/api/autonomous-paper-learning/scheduler/status")
    print("last_tick_at:", sched.get("last_tick_at"), "next:", sched.get("next_planned_at_utc"))
    print("enable_paper_scheduler_prod: PASS")


if __name__ == "__main__":
    main()
