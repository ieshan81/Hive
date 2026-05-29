"""Verify Research OS read/operator contract."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPERATOR_SECRET", "test-operator")
os.environ.setdefault("HIVE_ALLOW_UNAUTHENTICATED_DEV", "0")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


SPEC = {
    "strategy_id": "verify_push_pull_spec",
    "name": "Verify Push Pull Spec",
    "family": "pullback_push_pull",
    "asset_classes": ["crypto"],
    "timeframes": ["5Min"],
    "entry_logic": {"kind": "formula", "formula": "push_score > adaptive_threshold"},
    "exit_logic": {"kind": "dynamic", "formula": "atr_stop + target + trailing"},
    "risk_logic": {"kind": "paper_cage", "formula": "paper_only && live_locked"},
    "sizing_logic": {"kind": "bounded_formula", "formula": "min_notional_to_allocator"},
    "required_features": [{"name": "bars_5m", "min_rows": 14}],
}


def main() -> None:
    init_db()
    client = TestClient(app)
    status = client.get("/api/research/status")
    assert status.status_code == 200, status.text[:300]
    payload = status.json()
    assert payload.get("read_model_only") is True
    assert "optional_dependencies" in payload

    missing = client.post("/api/research/strategy-specs/create", json=SPEC)
    assert missing.status_code in (403, 503), missing.text[:300]

    created = client.post(
        "/api/research/strategy-specs/create",
        headers={"X-Operator-Token": "test-operator"},
        json={**SPEC, "actor": "operator"},
    )
    assert created.status_code == 200, created.text[:300]
    body = created.json()
    assert body["status"] == "ok"
    assert body["strategy_spec"]["strategy_id"] == SPEC["strategy_id"]

    ai_block = client.post(
        "/api/research/promotion/propose",
        headers={"X-Operator-Token": "test-operator"},
        json={"actor": "ai", "strategy_id": SPEC["strategy_id"], "from_stage": "idea", "to_stage": "paper_micro_trade"},
    )
    assert ai_block.status_code == 403, ai_block.text[:300]
    print("verify_research_os_contract: PASS")


if __name__ == "__main__":
    main()
