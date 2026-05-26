#!/usr/bin/env python3
"""Production acceptance: bar refresh, freshness, push-pull tick breakdown."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BACKEND = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app")
FRONTEND = os.environ.get("HIVE_FRONTEND", "https://melodious-happiness-production-0f5b.up.railway.app")


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=120) as res:
        return json.loads(res.read())


def post_operator(path: str, body: dict | None = None) -> dict:
    payload = json.dumps({"path": path, "body": body or {}}).encode()
    req = urllib.request.Request(
        f"{FRONTEND}/operator-proxy",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as res:
        return json.loads(res.read())


def main() -> int:
    failures: list[str] = []
    print("=== Production Bar Refresh Acceptance ===\n")

    try:
        refresh = post_operator(
            "/api/market-data/refresh-bars",
            {"asset_type": "crypto", "timeframe": "5Min", "lookback_hours": 48},
        )
    except urllib.error.HTTPError as exc:
        refresh = {"error": exc.read().decode()[:500]}
    print("refresh", json.dumps(refresh, indent=2)[:1200])

    if refresh.get("error"):
        failures.append(f"refresh_error:{refresh.get('error')[:80]}")
    elif refresh.get("reason") == "alpaca_not_configured":
        print("NOTE: Alpaca not configured — stale bars expected until keys set")
    else:
        if "refreshed_count" not in refresh:
            failures.append("refresh_missing_fields")

    fresh = get("/api/market-data/freshness?asset_type=crypto&timeframe=5Min")
    print(
        "\nfreshness fresh_count",
        fresh.get("fresh_count"),
        "stale_count",
        fresh.get("stale_count"),
    )
    btc = next((s for s in fresh.get("symbols", []) if s.get("symbol") == "BTC/USD"), None)
    if btc:
        print("BTC/USD", btc)

    if fresh.get("fresh_count", 0) == 0 and not refresh.get("provider_errors"):
        if refresh.get("reason") != "alpaca_not_configured":
            failures.append("zero_fresh_without_provider_error")

    uni = get("/api/universe/status")
    symbols = uni.get("symbols") or []
    fresh_uni = sum(1 for s in symbols if s.get("bar_freshness") == "fresh")
    stale_uni = sum(1 for s in symbols if s.get("bar_freshness") == "stale")
    print("\nuniverse", uni.get("total_symbols"), "fresh_bars", fresh_uni, "stale_bars", stale_uni)

    tick0 = get("/api/push-pull/latest-tick")
    t0 = tick0.get("tick_at")
    print("\nlatest_tick_before", tick0.get("plain"))
    print("  fresh_bar_count", tick0.get("fresh_bar_count"), "stale", tick0.get("stale_bar_count"))
    print("  eligible_strategies", tick0.get("eligible_strategy_count"))
    print("  breakdown", tick0.get("reason_breakdown"))

    if tick0.get("eligible_strategy_count", 0) == 0 and tick0.get("symbols_scanned_count"):
        # May update after deploy seed on next tick
        print("  (eligible_strategy_count 0 on last tick — waiting for new tick)")

    wait_s = int(os.environ.get("TICK_WAIT_SECONDS", "150"))
    print(f"\nwaiting {wait_s}s for scheduler tick...")
    time.sleep(wait_s)

    tick1 = get("/api/push-pull/latest-tick")
    print("\nlatest_tick_after", tick1.get("plain"))
    print("  fresh_bar_count", tick1.get("fresh_bar_count"), "stale", tick1.get("stale_bar_count"))
    print("  eligible_strategies", tick1.get("eligible_strategy_count"))
    print("  approved", tick1.get("approved_count"), "orders", tick1.get("order_count"))
    print("  breakdown", tick1.get("reason_breakdown"))

    if tick1.get("tick_at") == t0:
        print("  WARN: tick_at unchanged (scheduler may be slow)")

    if tick1.get("fresh_bar_count", 0) == 0 and fresh.get("fresh_count", 0) > 0:
        failures.append("tick_fresh_count_zero_but_freshness_ok")

    act = get("/api/activity/feed?limit=20")
    types = [e.get("event_type") for e in act.get("events", [])]
    print("\nactivity types", types[:12])
    for want in ("market_data_refresh", "strategy_eligibility", "tick"):
        if not any(want in (t or "") for t in types):
            print(f"  missing activity pattern: {want}")

    conf = get("/api/confidence/summary")
    lock = get("/api/settings/live-lock-tripwire")
    print("\nconfidence", conf.get("confidence_state"), "live_lock", lock.get("live_lock_status"))

    if lock.get("live_lock_status") != "locked":
        failures.append("live_not_locked")
    if lock.get("live_trading_enabled"):
        failures.append("live_enabled")

    if failures:
        print("\nFAILED:", failures)
        return 1
    print("\nPRODUCTION BAR REFRESH ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
