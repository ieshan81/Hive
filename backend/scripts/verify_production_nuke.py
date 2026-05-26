#!/usr/bin/env python3
"""Production app-level NUKE verification (via frontend operator proxy)."""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from typing import Any

FRONTEND = "https://melodious-happiness-production-0f5b.up.railway.app"
BACKEND = "https://hive-production-7343.up.railway.app"


def get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=90) as res:
        return json.loads(res.read())


def post_operator(path: str, body: dict | None = None) -> dict[str, Any]:
    payload = json.dumps({"path": path, "body": body or {}}).encode()
    req = urllib.request.Request(
        f"{FRONTEND}/operator-proxy",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.loads(res.read())


def main() -> None:
    print("=== PRE-NUKE nuke_status (from diagnostic export keys via graph meta) ===")
    graph_pre = get("/api/hive-brain/graph")
    print("graph", graph_pre.get("fresh_brain"), "nodes", len(graph_pre.get("nodes") or []))

    print("\n=== NUKE ===")
    nuke = post_operator("/api/danger-zone/nuke-everything", {"confirmation": "NUKE CAGED HIVE"})
    print(json.dumps(
        {
            "status": nuke.get("status"),
            "fresh_brain": nuke.get("fresh_brain"),
            "message": nuke.get("message"),
            "reset_epoch_id": nuke.get("reset_epoch_id"),
            "nuke_completed_at": nuke.get("nuke_completed_at"),
            "reset_epoch": nuke.get("reset_epoch"),
            "live_lock_status": nuke.get("live_lock_status"),
            "desired_learning_enabled": nuke.get("desired_learning_enabled"),
            "desired_scheduler_enabled": nuke.get("desired_scheduler_enabled"),
            "post_nuke_counts_sample": {
                k: nuke.get("post_nuke_counts", {}).get(k)
                for k in (
                    "lesson_nodes",
                    "ai_memories",
                    "execution_logs",
                    "orders",
                    "broker_errors",
                    "settings_actions_audit",
                )
            },
        },
        indent=2,
    ))

    print("\n=== POST-NUKE GETs ===")
    mc = get("/api/mission-control/status")
    ai = get("/api/ai-manager/status")
    mem = get("/api/ai-manager/memories")
    les = get("/api/ai-manager/lessons")
    graph = get("/api/hive-brain/graph")
    lock = get("/api/settings/live-lock-tripwire")

    checks = {
        "mission_control.fresh_brain": mc.get("fresh_brain"),
        "ai_manager.memories_count": mem.get("count"),
        "ai_manager.lessons_count": les.get("count"),
        "hive_brain.fresh_brain": graph.get("fresh_brain"),
        "hive_brain.learned_memory_nodes": graph.get("learned_memory_nodes"),
        "hive_brain.nodes": len(graph.get("nodes") or []),
        "hive_brain.edges": len(graph.get("edges") or []),
        "live_lock": lock.get("live_lock_status"),
        "paper_broker": lock.get("paper_broker"),
    }
    print(json.dumps(checks, indent=2))

    print("\n=== DIAGNOSTIC BUNDLE ===")
    with urllib.request.urlopen(f"{BACKEND}/api/diagnostic-bundle/download", timeout=180) as res:
        data = res.read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    for name in (
        "nuke_status.json",
        "reset_epoch.json",
        "post_nuke_table_counts.json",
        "ai_memory.json",
        "push_pull_lessons.json",
    ):
        if name in zf.namelist():
            content = json.loads(zf.read(name))
            print(name, json.dumps(content, indent=2)[:800])
        else:
            print(name, "MISSING")

    print("\n=== RESUME PAPER LEARNING ===")
    en = post_operator("/api/autonomous-paper-learning/enable", {})
    sched = post_operator("/api/autonomous-paper-learning/scheduler/enable", {})
    print("enable", en.get("status"), en.get("mode_enabled") if "mode_enabled" in en else en)
    print("scheduler_enable", sched.get("status"), sched.get("scheduler_enabled") if "scheduler_enabled" in sched else sched)

    print("\n=== TICK ===")
    tick = post_operator("/api/autonomous-paper-learning/scheduler/tick", {})
    print(json.dumps(
        {
            "status": tick.get("status"),
            "reason": tick.get("reason"),
            "tick": tick.get("tick"),
            "cycle_result_status": (tick.get("cycle_result") or {}).get("status"),
        },
        indent=2,
    )[:1200])

    print("\n=== POST-TICK ===")
    mem2 = get("/api/ai-manager/memories")
    les2 = get("/api/ai-manager/lessons")
    graph2 = get("/api/hive-brain/graph")
    nuke2 = json.loads(zf.read("nuke_status.json")) if "nuke_status.json" in zf.namelist() else {}
    # refresh nuke status
    with urllib.request.urlopen(f"{BACKEND}/api/diagnostic-bundle/download", timeout=180) as res:
        zf2 = zipfile.ZipFile(io.BytesIO(res.read()))
        nuke_status = json.loads(zf2.read("nuke_status.json"))
    print("nuke_status", json.dumps(nuke_status, indent=2))
    print("memories_after_tick", mem2.get("count"))
    if mem2.get("memories"):
        print("first_memory", mem2["memories"][0])
    sched_st = get("/api/autonomous-paper-learning/scheduler/status")
    print("scheduler", json.dumps(sched_st, indent=2)[:600])


if __name__ == "__main__":
    main()
