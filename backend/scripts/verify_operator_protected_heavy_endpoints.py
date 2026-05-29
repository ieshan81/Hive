"""Verify heavy operator endpoints reject missing operator auth."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


def main() -> None:
    init_db()
    client = TestClient(app)
    for path in (
        "/api/universe/refresh",
        "/api/universe/score",
        "/api/diagnostics/export/run",
        "/api/autonomous-paper-learning/run-one-cycle",
        "/api/lab/backtest/run",
        "/api/scanners/run-once",
        "/api/paper-learning/enable",
        "/api/research/backtests/run",
        "/api/research/agent-loop/run-dry",
        "/api/research/code-proposals/create",
        "/api/tradingview/webhook",
        "/api/live-flags/dry-run",
    ):
        res = client.post(path, json={})
        assert res.status_code in (403, 503), (path, res.status_code, res.text[:200])
    print("verify_operator_protected_heavy_endpoints: PASS")


if __name__ == "__main__":
    main()
