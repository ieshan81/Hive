"""Verify live flags remain locked and operator gated."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPERATOR_SECRET", "test-operator")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app
from app.services.live_flags_service import CONFIRMATION_PHRASE


def main() -> None:
    init_db()
    client = TestClient(app)
    status = client.get("/api/live-flags/status")
    assert status.status_code == 200, status.text[:300]
    assert status.json()["live_locked"] is True
    assert status.json()["live_trading_enabled"] is False

    no_auth = client.post("/api/live-flags/dry-run", json={})
    assert no_auth.status_code in (403, 503), no_auth.text[:300]

    wrong_phrase = client.post(
        "/api/live-flags/dry-run",
        headers={"X-Operator-Token": "test-operator"},
        json={"actor_type": "operator", "requested_flags": {"live_trading_enabled": True}},
    )
    assert wrong_phrase.status_code == 200
    assert "CONFIRMATION_PHRASE_REQUIRED" in wrong_phrase.json()["blockers"]
    assert wrong_phrase.json()["would_mutate"] is False

    ai = client.post(
        "/api/live-flags/request-change",
        headers={"X-Operator-Token": "test-operator"},
        json={
            "actor_type": "ai",
            "confirmation_phrase": CONFIRMATION_PHRASE,
            "requested_flags": {"live_trading_enabled": True},
        },
    )
    assert ai.status_code == 200
    body = ai.json()
    assert body["status"] == "rejected"
    assert "AI_ACTOR_FORBIDDEN" in body["blockers"]
    assert body["live_flags_changed"] is False
    print("verify_live_flags_locked: PASS")


if __name__ == "__main__":
    main()
