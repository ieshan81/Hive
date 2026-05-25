"""Pre-run readiness: operator auth, order display, no public secrets."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

BACKEND = os.environ.get("HIVE_API_URL", "https://hive-production-7343.up.railway.app").rstrip("/")
# melodious-happiness public domain may point at a non-Hive app; set HIVE_FRONTEND_URL to your Next.js service URL.
FRONTEND = os.environ.get("HIVE_FRONTEND_URL", "http://127.0.0.1:3001").rstrip("/")


def check_no_public_operator_secret() -> None:
    bad = []
    for pattern in ("NEXT_PUBLIC_OPERATOR", "NEXT_PUBLIC_OPERATOR_TOKEN"):
        for path in ROOT.rglob("*"):
            if path.suffix not in (".ts", ".tsx", ".js", ".jsx", ".env.example"):
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "scripts" in path.parts or path.name.startswith("verify_"):
                continue
            if pattern in text:
                bad.append(str(path.relative_to(ROOT)))
    if bad:
        raise AssertionError(f"NEXT_PUBLIC operator token in source: {bad}")


def check_order_display_labels() -> None:
    from app.services.order_display import order_status_label, order_type_label

    assert order_status_label("paper_order_rejected") == "Paper order rejected"
    assert order_status_label("preflight_blocked") == "Blocked by safety check before broker"
    assert order_type_label("marketable_limit_ioc") == "Instant market-price limit order"


def check_orders_panel_source() -> None:
    orders_panel = ROOT / "src" / "components" / "panels" / "OrdersPanel.tsx"
    text = orders_panel.read_text(encoding="utf-8")
    assert "OrderMetricsBar" in text
    assert "ExecutionOrdersTable" in text
    assert "paper_order_rejected" not in text


def check_operator_proxy_route() -> None:
    route = ROOT / "src" / "app" / "operator-proxy" / "route.ts"
    text = route.read_text(encoding="utf-8")
    assert "OPERATOR_SECRET" in text
    assert "NEXT_PUBLIC_OPERATOR" not in text


def http_json(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    import json
    import urllib.error
    import urllib.request

    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}


def check_production_apis() -> None:
    if os.environ.get("SKIP_PRODUCTION_CHECKS") == "1":
        return
    code, health = http_json(f"{BACKEND}/health")
    assert code == 200 and health.get("status") == "ok", health
    assert health.get("paper_trading_only") is True

    _, ft = http_json(f"{BACKEND}/api/fast-training/status")
    assert ft.get("training_mode_enabled") is False or ft.get("enabled") is False
    assert ft.get("entries_allowed") is False
    assert ft.get("can_submit_orders") is False

    _, lock = http_json(f"{BACKEND}/api/settings/live-lock-tripwire")
    assert lock.get("live_lock_status") == "locked" or lock.get("locked") is True

    _, pos = http_json(f"{BACKEND}/api/positions")
    assert (pos.get("count") or len(pos.get("positions") or [])) == 0

    for path in (
        "/api/fast-training/enable",
        "/api/fast-training/run-once",
        "/api/fast-training/exit-only/enable",
        "/api/cycle/run",
        "/api/settings/clear-ghost-rows",
    ):
        c, _ = http_json(f"{BACKEND}{path}", method="POST", body={})
        assert c in (401, 403, 503), f"{path} expected blocked got {c}"

    c, resync = http_json(f"{BACKEND}/api/settings/resync-broker-truth", method="POST", body={})
    assert c == 200 and resync.get("status") == "ok"
    assert resync.get("orders_created", 0) == 0


def check_frontend_proxy() -> None:
    if os.environ.get("SKIP_PRODUCTION_CHECKS") == "1":
        return
    code, data = http_json(f"{FRONTEND}/operator-proxy")
    if code == 404 and "HazardSnap" in str(data):
        raise AssertionError(
            "HIVE_FRONTEND_URL points at wrong Railway app (HazardSnap). "
            "Set HIVE_FRONTEND_URL to the Hive Next.js service domain."
        )
    assert code == 200, data
    for key in data:
        assert key.lower() not in ("operator_secret", "x_operator_token", "alpaca_secret_key")
    configured = data.get("server_operator_auth_configured") or data.get("proxy_configured")
    print(f"operator_proxy_configured={configured}")


def main() -> None:
    check_no_public_operator_secret()
    check_order_display_labels()
    check_orders_panel_source()
    check_operator_proxy_route()
    check_production_apis()
    check_frontend_proxy()
    print("ALL_PRE_RUN_CHECKS_PASSED")


if __name__ == "__main__":
    main()
