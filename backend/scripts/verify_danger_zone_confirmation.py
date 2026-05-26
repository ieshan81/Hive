#!/usr/bin/env python3
"""Danger zone confirmation phrases — backend only (no nuke on success path in CI)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["OPERATOR_SECRET"] = "test-operator-secret-for-ci"

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
import app.database as db_module


def main():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    db_module.engine = engine
    client = TestClient(app)
    headers = {"X-Operator-Token": "test-operator-secret-for-ci"}

    r = client.post("/api/danger-zone/nuke-everything", json={"confirmation": "WRONG"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refused"
    assert r.json()["reason"] == "confirmation_phrase_mismatch"

    r2 = client.post(
        "/api/danger-zone/ready-for-live-cleanup",
        json={"confirmation": "WRONG"},
        headers=headers,
    )
    assert r2.json()["status"] == "refused"

    lock = client.get("/api/settings/live-lock-tripwire")
    assert lock.json().get("live_lock_status") == "locked"
    assert lock.json().get("live_trading_enabled") is False

    print("OK danger_zone_confirmation")
    print("ALL DANGER ZONE BACKEND CHECKS PASSED")


if __name__ == "__main__":
    main()
