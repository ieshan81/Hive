"""Pre-flight checklist before operator-approved paper run-once (does not enable training or run-once)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = os.environ.get("HIVE_API_URL", "https://hive-production-7343.up.railway.app").rstrip("/")
FRONTEND = os.environ.get("HIVE_FRONTEND_URL", "http://127.0.0.1:3001").rstrip("/")


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


def main() -> None:
    failures: list[str] = []

    _, lock = http_json(f"{BACKEND}/api/settings/live-lock-tripwire")
    if lock.get("live_lock_status") != "locked":
        failures.append("live_lock_not_locked")

    if not lock.get("paper_broker"):
        failures.append("paper_broker_not_yes")

    _, ft = http_json(f"{BACKEND}/api/fast-training/status")
    if ft.get("training_mode_enabled"):
        failures.append("training_already_on")
    _, eo = http_json(f"{BACKEND}/api/fast-training/exit-only/status")
    if eo.get("exit_only_enabled"):
        failures.append("exit_only_on")

    _, pos = http_json(f"{BACKEND}/api/positions")
    if (pos.get("count") or 0) > 0:
        failures.append("open_broker_positions")

    _, truth = http_json(f"{BACKEND}/api/reconciliation/broker-truth")
    ghosts = truth.get("ghost_position_candidates") or []
    if ghosts:
        failures.append("ghost_candidates_present")

    from datetime import date

    from app.services.session_engine import SessionEngine

    st = SessionEngine().detect()
    if date.today().year <= 2026 and not st.calendar_available:
        failures.append("calendar_unavailable_today")

    if os.environ.get("SKIP_FRONTEND_PROXY") == "1":
        proxy = {"server_operator_auth_configured": False, "skipped": True}
    else:
        try:
            code, proxy = http_json(f"{FRONTEND}/operator-proxy")
        except Exception as exc:
            failures.append(f"operator_proxy_unreachable:{exc}")
            proxy = {}
        else:
            if code != 200:
                failures.append(f"operator_proxy_http_{code}")
            elif not (proxy.get("server_operator_auth_configured") or proxy.get("proxy_configured")):
                failures.append("operator_proxy_not_configured")

    root = Path(__file__).resolve().parents[2]
    for path in root.rglob("*"):
        if path.suffix not in (".ts", ".tsx") or "node_modules" in path.parts:
            continue
        try:
            if "NEXT_PUBLIC_OPERATOR" in path.read_text(encoding="utf-8", errors="ignore"):
                failures.append("next_public_operator_in_source")
                break
        except OSError:
            pass

    _, orders_before = http_json(f"{BACKEND}/api/orders?limit=100")
    count_before = orders_before.get("count", 0)

    if failures:
        print("NOT_READY:", failures)
        sys.exit(1)

    print("READY_FOR_OPERATOR_APPROVED_PAPER_RUN_ONCE")
    print(f"orders_before={count_before}")
    print(f"us_stocks={st.to_dict().get('us_stocks_display')}")
    print(f"crypto={st.to_dict().get('crypto_display')}")
    print(f"operator_proxy_configured={proxy.get('server_operator_auth_configured')}")


if __name__ == "__main__":
    main()
