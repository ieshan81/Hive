#!/usr/bin/env python3
"""Production E2E: refresh bars + run cycle + prove order or exact blocker."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BACKEND = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app")
FRONTEND = os.environ.get("HIVE_FRONTEND", "https://melodious-happiness-production-0f5b.up.railway.app")


def get(path: str, timeout: int = 90) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as res:
        return json.loads(res.read())


def post_op(path: str, body: dict | None = None, timeout: int = 180) -> tuple[int, dict]:
    payload = json.dumps({"path": path, "body": body or {}}).encode()
    req = urllib.request.Request(
        f"{FRONTEND}/operator-proxy",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()[:2000] or "{}")


def main() -> int:
    print("=== Production E2E Order Proof ===\n")
    failures: list[str] = []

    health = get("/health", 30)
    print("health", health.get("paper_trading_only"), health.get("status"))

    lock = get("/api/settings/live-lock-tripwire", 30)
    print("live_lock", lock.get("live_lock_status"), "live_enabled", lock.get("live_trading_enabled"))
    if lock.get("live_lock_status") != "locked":
        failures.append("live_not_locked")

    code, refresh = post_op(
        "/api/market-data/refresh-bars",
        {"asset_type": "crypto", "timeframe": "5Min", "lookback_hours": 48},
        timeout=120,
    )
    print("refresh", code, "fresh", refresh.get("fresh_count"), "latest", refresh.get("latest_bar_time"))

    qf = get("/api/market-data/quote-freshness?asset_type=crypto", 60)
    print("quote_freshness", qf.get("fresh_count"), "/", qf.get("count"))

    proof0 = get("/api/push-pull/paper-order-proof", 60)
    print("proof_before", proof0.get("plain"))

    code, cycle = post_op("/api/autonomous-paper-learning/run-one-cycle", {"operator": "e2e_acceptance"}, timeout=120)
    print("cycle", code, "orders_created", cycle.get("orders_created"))
    ts = cycle.get("tick_summary") or {}
    print("tick", (ts.get("plain_summary") or "")[:200])
    print("  approved", ts.get("approved_count"), "orders", ts.get("order_count"))
    print("  breakdown", ts.get("reason_breakdown"))

    proof = get("/api/push-pull/paper-order-proof", 60)
    print("\nproof_after", proof.get("plain"))
    print("counts", proof.get("counts"))
    latest = proof.get("latest_submit") or {}
    block = proof.get("latest_preflight_block") or {}
    if latest.get("broker_order_id"):
        print("\nSUCCESS broker_order_id", latest.get("broker_order_id"))
        print("client", latest.get("broker_client_order_id"))
        print("status", latest.get("status"))
    elif proof.get("counts", {}).get("submitted_to_broker", 0) > 0:
        print("\nSUCCESS submitted_to_broker count > 0")
    else:
        diag = get("/api/push-pull/diagnosis", 60)
        print("\nNO BROKER SUBMIT — diagnosis:")
        print(diag.get("why_no_order"))
        print("next:", diag.get("operator_next_action"))
        if block:
            print("latest_block", block.get("reject_reason"), block.get("reject_reason_plain"))
            print("  blocked_before_broker", block.get("blocked_before_broker"))

    conf = get("/api/confidence/summary", 30)
    print("\nconfidence", conf.get("confidence_state"), "evidence", conf.get("evidence_count"))

    if failures:
        print("\nFAILED", failures)
        return 1
    return 0 if (latest.get("broker_order_id") or proof.get("counts", {}).get("submitted_to_broker")) else 2


if __name__ == "__main__":
    sys.exit(main())
