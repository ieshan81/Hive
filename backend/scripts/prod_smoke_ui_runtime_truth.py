"""Post-deploy prod smoke for UI/runtime truth PR — no secrets printed."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://hive-production-7343.up.railway.app"
UI = "https://melodious-happiness-production-0f5b.up.railway.app"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    runtime = get("/api/runtime/summary")
    paper = get("/api/execution/paper/status")
    prod = get("/api/paper-validation/productivity")
    shadow = get("/api/shadow-league/status")
    uni = get("/api/universe/summary")
    sched = get("/api/autonomous-paper-learning/scheduler/status")

    with urllib.request.urlopen(f"{BASE}/api/diagnostics/bundle?mode=latest&format=json", timeout=180) as r:
        bundle = json.loads(r.read())
    readme = bundle.get("README_FIRST.json") or {}
    meta = bundle.get("bundle_meta.json") or {}

    with urllib.request.urlopen(f"{BASE}/api/diagnostic-bundle/download?mode=latest", timeout=180) as r:
        zdata = r.read()
    z = zipfile.ZipFile(io.BytesIO(zdata))

    pages = [
        "/mission-control",
        "/universe",
        "/shadow-league",
        "/paper-candidates",
        "/risk-cage",
        "/evidence-memory",
        "/diagnostics",
        "/engine-map",
        "/tradingview",
    ]
    ui_ok = {}
    for p in pages:
        try:
            req = urllib.request.Request(f"{UI}{p}")
            with urllib.request.urlopen(req, timeout=60) as r:
                ui_ok[p] = r.status
        except urllib.error.HTTPError as e:
            ui_ok[p] = e.code
        except Exception as e:
            ui_ok[p] = str(e)[:40]

    graph_ok = False
    try:
        with urllib.request.urlopen(f"{BASE}/api/evidence-memory/graph?mode=research", timeout=60) as r:
            g = json.loads(r.read())
            graph_ok = r.status == 200 and g.get("status") in ("ok", "degraded")
    except Exception:
        graph_ok = False

    report = {
        "deployed_commit": readme.get("git_commit"),
        "runtime_summary": {
            "broker_connected": runtime.get("broker_connected"),
            "paper_broker": runtime.get("paper_broker"),
            "broker_mode": runtime.get("broker_mode"),
            "live_locked": runtime.get("live_locked"),
            "scheduler_enabled": runtime.get("scheduler_enabled"),
            "paper_entry_ready": runtime.get("paper_entry_ready"),
            "paper_candidate_count": runtime.get("paper_candidate_count"),
            "shadow_league_enabled": runtime.get("shadow_league_enabled"),
            "shadow_ui_state": runtime.get("shadow_ui_state"),
            "data_degraded": runtime.get("data_degraded"),
        },
        "scheduler_last_tick_at": sched.get("last_tick_at"),
        "shadow_count": shadow.get("shadow_league_count"),
        "reason_shadow_count_zero": shadow.get("reason_shadow_count_zero"),
        "universe_funnel": uni.get("funnel_counts"),
        "paper_candidates": prod.get("paper_candidates"),
        "paper_entry_ready_productivity": prod.get("paper_entry_ready"),
        "live_orders_enabled": paper.get("live_orders_enabled"),
        "current_run_order_attempts": (bundle.get("current_run_trade_truth.json") or {}).get("current_run_order_attempts"),
        "bundle_generation_seconds": meta.get("generation_seconds"),
        "bundle_file_count": len(z.namelist()),
        "bundle_size_bytes": len(zdata),
        "evidence_memory_graph_ok": graph_ok,
        "ui_pages": ui_ok,
    }
    print(json.dumps(report, indent=2))

    assert runtime.get("live_locked") is True
    assert paper.get("live_orders_enabled") is False
    assert runtime.get("scheduler_enabled") is True
    assert runtime.get("paper_broker") is True
    assert shadow.get("enabled") is True
    assert graph_ok
    assert all(v == 200 for v in ui_ok.values())
    assert int((bundle.get("current_run_trade_truth.json") or {}).get("current_run_order_attempts") or 0) == 0
    print("prod_smoke_ui_runtime_truth: PASS")


if __name__ == "__main__":
    main()
