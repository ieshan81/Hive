#!/usr/bin/env python3
"""Run acceptance-gap proof via frontend operator-proxy (no secret in logs)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BACKEND = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app")
FRONTEND = os.environ.get("HIVE_FRONTEND", "https://melodious-happiness-production-0f5b.up.railway.app")


def get(path: str, timeout: int = 90) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as res:
        return json.loads(res.read())


def post_op(path: str, body: dict | None = None, timeout: int = 300) -> tuple[int, dict]:
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
        raw = e.read().decode()[:4000]
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": raw}


def main() -> int:
    print("=== Acceptance Gaps Proof ===\n")
    failures: list[str] = []

    bt_before = get("/api/backtesting/status", 60)
    count_before = int(bt_before.get("backtest_run_count") or 0)
    print("backtest_run_count_before", count_before)

    lock = get("/api/settings/live-lock-tripwire", 30)
    print("live_lock", lock.get("live_lock_status"), "live_enabled", lock.get("live_trading_enabled"))
    if lock.get("live_lock_status") != "locked":
        failures.append("live_not_locked")
    if lock.get("live_trading_enabled"):
        failures.append("live_trading_enabled_true")

    code, bt_run = post_op(
        "/api/backtesting/run-push-pull",
        {
            "symbols": ["BTC/USD", "ETH/USD"],
            "timeframe": "5Min",
            "lookback_days": 90,
            "strategy_id": "crypto_push_pull_baseline",
        },
        timeout=300,
    )
    print("run-push-pull", code, bt_run.get("status"), "run_id", bt_run.get("run_id"))
    if code == 403:
        failures.append("backtest_403_operator_auth")
    metrics = bt_run.get("metrics") or (bt_run.get("result") or {}).get("metrics") or {}
    print(
        "  trades", metrics.get("num_trades"),
        "win_rate", metrics.get("win_rate"),
        "expectancy", metrics.get("expectancy"),
        "pf", metrics.get("profit_factor"),
        "dd", metrics.get("max_drawdown"),
        "result_label", metrics.get("result_label"),
    )

    bt_after = get("/api/backtesting/status", 60)
    count_after = int(bt_after.get("backtest_run_count") or 0)
    print("backtest_run_count_after", count_after)
    if count_after <= count_before and code == 200:
        failures.append("backtest_count_not_increased")

    runs = get("/api/backtesting/runs?limit=3", 60)
    latest = (runs.get("runs") or [{}])[0]
    print("latest_run", latest.get("run_id"), latest.get("symbols"), latest.get("result_label"))

    ai_mgr = get("/api/ai-manager/status", 60)
    print("ai_manager lessons", ai_mgr.get("recent_lessons_count"))

    strat_perf = get("/api/trading-cage/strategy-performance", 60)
    print("strategy_performance strategies", len(strat_perf.get("strategies") or []))

    code, refresh = post_op(
        "/api/market-data/refresh-bars",
        {"asset_type": "crypto", "timeframe": "5Min", "lookback_hours": 48},
        timeout=180,
    )
    print("refresh-bars", code, refresh.get("fresh_count"), refresh.get("latest_bar_time"))

    code, cycle = post_op(
        "/api/autonomous-paper-learning/run-one-cycle",
        {"operator": "acceptance_gaps"},
        timeout=180,
    )
    print("run-one-cycle", code, "orders_created", cycle.get("orders_created"))
    ts = cycle.get("tick_summary") or {}
    print("  scoring_model", ts.get("scoring_model"))
    print("  top", (ts.get("top_candidate") or {}).get("symbol"), (ts.get("top_candidate") or {}).get("trade_quality_score"))
    print("  plain", (ts.get("plain_summary") or "")[:220])
    print("  breakdown", ts.get("reason_breakdown"))

    tick = get("/api/push-pull/latest-tick", 60)
    print("latest-tick scoring_model", tick.get("scoring_model"))

    strat = get("/api/strategy/status", 60)
    print("strategy live_scoring", strat.get("live_scoring_model"), "on_path", strat.get("scoring_on_live_path"))

    mc = get("/api/mission-control/status", 90)
    print("mission_control ok", mc.get("status") == "ok")

    recon = get("/api/portfolio/reconciliation", 60)
    print("portfolio_reconciliation warning", recon.get("reconciliation_warning"))

    card = get("/api/activity/latest-tick-card", 60)
    print("activity_card why", (card.get("why") or "")[:120])

    sent = get("/api/sentiment/status", 30)
    print("sentiment", sent.get("display_title"))

    print("\n=== Summary ===")
    print("backtest before/after", count_before, "->", count_after)
    print("paper_order", "yes" if (cycle.get("orders_created") or 0) > 0 else "no")
    if failures:
        print("FAILED", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
