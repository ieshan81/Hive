"""Verify controlled agent graph cannot trade or change live flags."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPERATOR_SECRET", "test-operator")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


def main() -> None:
    init_db()
    client = TestClient(app)
    missing = client.post("/api/research/agent-loop/run-dry", json={})
    assert missing.status_code in (403, 503), missing.text[:300]

    res = client.post(
        "/api/research/agent-loop/run-dry",
        headers={"X-Operator-Token": "test-operator"},
        json={"actor": "operator", "hypothesis": "dry safety verification"},
    )
    assert res.status_code == 200, res.text[:300]
    body = res.json()
    assert body["orders_submitted"] == 0
    assert body["live_flags_changed"] is False
    assert body["capabilities"]["submit_orders"] is False
    assert body["capabilities"]["change_live_flags"] is False

    live = client.post(
        "/api/live-flags/request-change",
        headers={"X-Operator-Token": "test-operator"},
        json={"actor_type": "ai", "requested_flags": {"live_trading_enabled": True}},
    )
    assert live.status_code == 200, live.text[:300]
    assert live.json()["status"] == "rejected"
    assert live.json()["live_flags_changed"] is False
    print("verify_ai_agent_safety: PASS")


if __name__ == "__main__":
    main()
