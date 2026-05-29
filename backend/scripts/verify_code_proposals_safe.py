"""Verify code proposals are draft-only and cannot self-apply."""

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
    payload = {
        "actor": "operator",
        "title": "Verify draft proposal",
        "description": "Test-only draft",
        "affected_files": ["backend/app/example.py"],
        "diff_text": "--- a/example.py\n+++ b/example.py\n",
        "tests_required": ["python -m compileall app"],
        "risk_assessment": {"risk": "low"},
    }
    no_auth = client.post("/api/research/code-proposals/create", json=payload)
    assert no_auth.status_code in (403, 503), no_auth.text[:300]

    created = client.post(
        "/api/research/code-proposals/create",
        headers={"X-Operator-Token": "test-operator"},
        json=payload,
    )
    assert created.status_code == 200, created.text[:300]
    body = created.json()
    assert body["applied"] is False
    assert body["merged"] is False
    assert body["deployed"] is False
    pid = body["proposal"]["proposal_id"]

    ai_approve = client.post(
        "/api/research/code-proposals/approve-draft",
        headers={"X-Operator-Token": "test-operator"},
        json={"actor": "ai", "proposal_id": pid},
    )
    assert ai_approve.status_code == 403, ai_approve.text[:300]

    approve = client.post(
        "/api/research/code-proposals/approve-draft",
        headers={"X-Operator-Token": "test-operator"},
        json={"actor": "operator", "proposal_id": pid},
    )
    assert approve.status_code == 200, approve.text[:300]
    assert approve.json()["applied"] is False
    print("verify_code_proposals_safe: PASS")


if __name__ == "__main__":
    main()
