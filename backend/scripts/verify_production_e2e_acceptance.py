#!/usr/bin/env python3
"""Production end-to-end acceptance checks (read-only + optional start-fresh via proxy)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BACKEND = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app")
FRONTEND = os.environ.get("HIVE_FRONTEND", "https://melodious-happiness-production-0f5b.up.railway.app")


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=90) as res:
        return json.loads(res.read())


def post_operator(path: str, body: dict | None = None) -> dict:
    payload = json.dumps({"path": path, "body": body or {}}).encode()
    req = urllib.request.Request(
        f"{FRONTEND}/operator-proxy",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.loads(res.read())


def main() -> int:
    failures: list[str] = []
    print("=== Production E2E Acceptance ===\n")

    health = get("/health")
    print("health", health.get("status"), "paper_only", health.get("paper_trading_only"))
    if health.get("paper_trading_only") is not True:
        failures.append("health not paper_only")

    mc = get("/api/mission-control/status")
    print("mission_control mode", mc.get("current_mode"))
    print("can_place", mc.get("can_place_paper_orders"))
    print("primary", mc.get("primary_blocker_plain"))
    print("learning", mc.get("paper_learning"))
    if not mc.get("primary_blocker_plain") and mc.get("can_place_paper_orders") is False:
        failures.append("missing primary_blocker when cannot place orders")

    conf = get("/api/confidence/summary")
    print("confidence", conf.get("confidence_state"), conf.get("overall_label"), "evidence", conf.get("evidence_count"))
    if conf.get("confidence_state") == "no_evidence" and conf.get("overall") not in (None, 0):
        failures.append("no_evidence but overall score set")

    uni = get("/api/universe/status")
    total = uni.get("total_symbols") or uni.get("counts", {}).get("total", 0)
    print("universe total", total, "crypto", uni.get("counts", {}).get("crypto"))
    if total == 0:
        failures.append("universe empty")

    lock = get("/api/settings/live-lock-tripwire")
    print("live_lock", lock.get("live_lock_status"), "live_enabled", lock.get("live_trading_enabled"))
    if lock.get("live_lock_status") != "locked":
        failures.append("live not locked")
    if lock.get("live_trading_enabled"):
        failures.append("live trading enabled")

    tick = get("/api/push-pull/latest-tick")
    print("last_tick", tick.get("plain"), "scanned", tick.get("symbols_scanned_count"))

    act = get("/api/activity/feed?limit=10")
    print("activity events", act.get("count"))

    perf = get("/api/performance/summary")
    print("performance equity", perf.get("current_equity"), perf.get("fresh_baseline_label"))

    # Optional: observe scheduler (2 intervals ~5min — skip in quick mode)
    if os.environ.get("OBSERVE_TICKS") == "1":
        sched = mc.get("scheduler") or {}
        t0 = sched.get("last_tick_at")
        print("waiting 6m for tick...", t0)
        time.sleep(360)
        mc2 = get("/api/mission-control/status")
        t1 = (mc2.get("scheduler") or {}).get("last_tick_at")
        print("tick after wait", t1)
        if t0 == t1:
            failures.append("scheduler did not tick in 6 minutes")

    if failures:
        print("\nFAILED:", failures)
        return 1
    print("\nALL PRODUCTION E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
