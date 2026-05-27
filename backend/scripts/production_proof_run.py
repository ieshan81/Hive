#!/usr/bin/env python3
"""Full production proof — read-only checks against live Railway."""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from typing import Any

BACKEND = os.environ.get("HIVE_BACKEND", "https://hive-production-7343.up.railway.app")
FRONTEND = os.environ.get("HIVE_FRONTEND", "https://melodious-happiness-production-0f5b.up.railway.app")

KEY_BUNDLE_FILES = [
    "bundle_meta.json",
    "health_snapshot.json",
    "live_lock_status.json",
    "push_pull_latest_tick.json",
    "ai_memory.json",
    "crypto_readiness.json",
    "targeted_experiment_status.json",
    "mission_control_status.json",
    "hybrid_radar_snapshot.json",
    "diagnostic_export_errors.json",
]

FRONTEND_ROUTES = [
    "/",
    "/universe",
    "/push-pull",
    "/performance",
    "/reports",
    "/control-center",
    "/market-radar",
    "/settings",
]


def get(path: str, timeout: float = 90) -> tuple[dict[str, Any], int]:
    t0 = time.perf_counter()
    with urllib.request.urlopen(BACKEND + path, timeout=timeout) as res:
        data = json.loads(res.read())
    return data, int((time.perf_counter() - t0) * 1000)


def safe(label: str, fn, failures: list[str], *, fatal: bool = False) -> Any:
    try:
        return fn()
    except Exception as exc:
        err = f"{label}: {type(exc).__name__}: {str(exc)[:120]}"
        if fatal:
            failures.append(err)
        return {"error": err}


def fetch_html(path: str, timeout: float = 30) -> tuple[int, str, int]:
    t0 = time.perf_counter()
    with urllib.request.urlopen(FRONTEND + path, timeout=timeout) as res:
        html = res.read().decode("utf-8", errors="replace")
    return res.status, html, int((time.perf_counter() - t0) * 1000)


def main() -> int:
    out: dict[str, Any] = {"backend": BACKEND, "frontend": FRONTEND}
    failures: list[str] = []

    # 1–2 Live lock + paper broker
    lock, ms = get("/api/live-lock/status", 15)
    out["live_lock"] = {
        "ms": ms,
        "live_lock_status": lock.get("live_lock_status"),
        "live_trading_enabled": lock.get("live_trading_enabled"),
        "paper_broker": lock.get("paper_broker"),
    }
    if lock.get("live_lock_status") != "locked":
        failures.append("live_lock not locked")
    if lock.get("paper_broker") is not True:
        failures.append("paper_broker not true")

    # 3 Hybrid radar
    mode, ms = get("/api/universe/mode", 15)
    out["hybrid_radar"] = {
        "ms": ms,
        "active_mode": mode.get("active_mode"),
        "total_symbols": mode.get("total_symbols") or mode.get("total"),
    }
    if mode.get("active_mode") != "hybrid_radar":
        failures.append("hybrid_radar not active")

    # 4 FinBERT
    sent, ms = get("/api/sentiment/status", 15)
    fb = sent.get("finbert") or {}
    out["finbert"] = {"ms": ms, "active": fb.get("active"), "connected": fb.get("connected")}
    if not fb.get("active"):
        failures.append("finbert not active")

    # 5 Reddit
    reddit, ms = get("/api/social/reddit/status", 15)
    out["reddit"] = {k: reddit.get(k) for k in ("status", "mode", "active", "read_only", "last_scan_at")}
    out["reddit"]["ms"] = ms

    # 6 News
    news, ms = get("/api/news/status", 15)
    out["news"] = {k: news.get(k) for k in ("status", "mode", "active", "last_scan_at", "headlines_count")}
    out["news"]["ms"] = ms

    # 7 Crypto readiness
    try:
        crypto, ms = get("/api/crypto/readiness", 120)
        out["crypto_readiness"] = {
            "ms": ms,
            "http": 200,
            "status": crypto.get("status"),
            "paper_trade_allowed": crypto.get("paper_trade_allowed"),
            "degraded": crypto.get("degraded"),
            "reason": crypto.get("reason") or crypto.get("primary_reason"),
        }
    except Exception as exc:
        out["crypto_readiness"] = {"http_error": str(exc)[:200]}
        failures.append("crypto_readiness not 200")

    # 8 Stocks readiness
    stocks, ms = get("/api/stocks/readiness", 30)
    out["stocks_readiness"] = {"ms": ms, "status": stocks.get("status"), "market_open": stocks.get("market_open")}

    # 9–10 Universe radar + lesser-known
    radar, ms = get("/api/universe/radar", 90)
    symbols = radar.get("symbols") or radar.get("ranked") or []
    sym_list = [s.get("symbol") if isinstance(s, dict) else s for s in symbols] if isinstance(symbols, list) else []
    highlights = radar.get("lesser_known_highlights") or []
    out["universe_radar"] = {
        "ms": ms,
        "count": len(sym_list) or radar.get("symbol_count") or radar.get("total_symbols"),
        "lesser_known_highlights": highlights[:10],
        "hype_present": any("HYPE" in str(x) for x in sym_list + highlights),
        "render_present": any("RENDER" in str(x) for x in sym_list + highlights),
    }
    if not out["universe_radar"]["count"]:
        failures.append("universe radar empty")

    # 11 Targeted experiment
    exp_st, ms = get("/api/research/targeted-experiment/status", 15)
    exp_lt, ms2 = get("/api/research/targeted-experiment/latest", 15)
    out["targeted_experiment"] = {
        "status_endpoint": exp_st,
        "latest": {k: exp_lt.get(k) for k in (
            "status", "symbols", "plain_verdict", "primary_blocker", "orders_placed",
            "research_only", "completed_at", "message",
        ) if exp_lt.get(k) is not None},
        "ms_status": ms,
        "ms_latest": ms2,
    }

    # 12 Push-pull verdict (may be slow — non-fatal timeout)
    def _verdict():
        v, ms = get("/api/strategy/push-pull/verdict", 45)
        return {
            "ms": ms,
            "status": v.get("status"),
            "verdict": v.get("verdict"),
            "plain": (v.get("plain") or v.get("plain_verdict") or "")[:240],
        }

    out["push_pull_verdict"] = safe("push_pull_verdict", _verdict, failures)
    if "error" not in out["push_pull_verdict"]:
        tick, tms = get("/api/push-pull/latest-tick", 20)
        out["push_pull_latest_tick"] = {
            "ms": tms,
            "plain": (tick.get("plain") or "")[:200],
            "symbols_scanned_count": tick.get("symbols_scanned_count"),
        }

    # 13 Memory graph research/skeleton
    graph, ms = get("/api/hive-brain/graph", 90)
    meta = graph.get("meta") or {}
    nodes = graph.get("nodes") or []
    out["hive_brain_graph"] = {
        "ms": ms,
        "node_count": len(nodes),
        "fresh_brain": graph.get("fresh_brain"),
        "layout_mode": meta.get("layout_mode"),
        "graph_mode": meta.get("graph_mode"),
        "system_skeleton_nodes": meta.get("system_skeleton_nodes"),
        "message": (graph.get("message") or "")[:160],
        "research_leads": [n.get("label") for n in nodes if n.get("type") == "research_lead"][:6],
    }
    brain_st, _ = get("/api/hive-brain/status", 30)
    out["hive_brain_status"] = {"visible_nodes": brain_st.get("visible_nodes"), "graph_meta": brain_st.get("graph_meta")}

    # 14–15 Diagnostic bundle
    try:
        bundle, ms = get("/api/diagnostic-bundle", 300)
        keys = list(bundle.keys()) if isinstance(bundle, dict) else []
        present = [f for f in KEY_BUNDLE_FILES if f in keys]
        missing = [f for f in KEY_BUNDLE_FILES if f not in keys]
        meta_file = bundle.get("bundle_meta.json") if isinstance(bundle.get("bundle_meta.json"), dict) else {}
        out["diagnostic_bundle_json"] = {
            "ms": ms,
            "file_count": len(keys),
            "partial": meta_file.get("partial"),
            "present_key_files": present,
            "missing_key_files": missing,
        }
    except Exception as exc:
        out["diagnostic_bundle_json"] = {"error": str(exc)[:300], "note": "use download zip or reports status"}
        try:
            hub, _ = get("/api/reports/diagnostic-bundle/status", 15)
            out["diagnostic_bundle_reports_status"] = {
                "expected_files": hub.get("expected_files"),
                "download_path": hub.get("download_path"),
            }
        except Exception:
            pass

    try:
        req = urllib.request.Request(BACKEND + "/api/diagnostic-bundle/download")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=300) as res:
            cd = res.headers.get("Content-Disposition", "")
            zbytes = res.read()
        dl_ms = int((time.perf_counter() - t0) * 1000)
        m = re.search(r'filename="?([^";]+)', cd)
        fname = m.group(1).strip() if m else "caged-hive-diagnostic.zip"
        zf = zipfile.ZipFile(io.BytesIO(zbytes))
        names = zf.namelist()
        out["diagnostic_bundle_zip"] = {
            "filename": fname,
            "download_ms": dl_ms,
            "zip_entry_count": len(names),
            "sample_entries": names[:15],
        }
    except Exception as exc:
        out["diagnostic_bundle_zip"] = {"error": str(exc)[:300]}
        # Non-fatal if JSON export also slow under load

    # Mission control regression (no changes — verify only)
    mc, ms = get("/api/mission-control/status", 15)
    out["mission_control_regression"] = {
        "ms": ms,
        "status": mc.get("status"),
        "snapshot_age_seconds": mc.get("snapshot_age_seconds"),
        "data_freshness": mc.get("data_freshness"),
    }
    if ms > 2000:
        failures.append("mission_control >2s")

    # 16–17 Frontend pages
    pages: list[dict[str, Any]] = []
    for route in FRONTEND_ROUTES:
        try:
            status, html, pms = fetch_html(route, 30)
            raw_json_heuristic = (
                html.strip().startswith("{")
                and '"status"' in html[:500]
                and "<!DOCTYPE" not in html[:200].upper()
            )
            pages.append({
                "route": route,
                "http": status,
                "ms": pms,
                "html_len": len(html),
                "looks_like_raw_json": raw_json_heuristic,
            })
            if status != 200:
                failures.append(f"frontend {route} not 200")
            if raw_json_heuristic:
                failures.append(f"frontend {route} raw json")
        except Exception as exc:
            pages.append({"route": route, "error": str(exc)[:120]})
            failures.append(f"frontend {route} failed")
    out["frontend_pages"] = pages

    out["failures"] = failures
    print(json.dumps(out, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
