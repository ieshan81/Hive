"""Verify TradingView events are display-only and cannot execute."""

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
    no_auth = client.post("/api/tradingview/webhook", json={"symbol": "BTC/USD", "side": "buy"})
    assert no_auth.status_code in (403, 503), no_auth.text[:300]

    res = client.post(
        "/api/tradingview/webhook",
        headers={"X-Operator-Token": "test-operator"},
        json={"symbol": "BTC/USD", "side": "buy", "timeframe": "5Min"},
    )
    assert res.status_code == 200, res.text[:300]
    body = res.json()
    assert body["accepted_for_display"] is True
    assert body["execution_attempted"] is False
    assert body["execution_blocked_reason"] == "display_only_execution_blocked"

    status = client.get("/api/tradingview/status")
    assert status.status_code == 200
    assert status.json()["execution_allowed"] is False
    print("verify_tradingview_execution_blocked: PASS")


if __name__ == "__main__":
    main()
