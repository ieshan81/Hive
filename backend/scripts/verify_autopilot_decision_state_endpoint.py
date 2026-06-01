"""Autopilot decision-state endpoint is read-only and returns operator-facing truth."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / f"hive_autopilot_decision_state_{os.getpid()}.db"
try:
    tmp_db.unlink()
except FileNotFoundError:
    pass

os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db.as_posix()}"
os.environ["LIVE_TRADING_ARMED"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.database import AccountSnapshot, TradeRecord, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    init_db()
    with Session(engine) as session:
        session.add(AccountSnapshot(equity=200, cash=200, buying_power=200, portfolio_value=200))
        session.add(
            TradeRecord(
                symbol="DOGE/USD",
                strategy="fixture",
                side="buy",
                entry_price=0.1,
                quantity=100,
                status="open",
            )
        )
        session.commit()
    client = TestClient(app)
    for path in ("/api/autonomous-paper-learning/decision-state", "/api/autopilot/decision-state"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code, resp.text[:500])
        data = resp.json()
        assert data["status"] == "ok", data
        assert data["current_mode"] == "paper", data
        assert "stale_local_state" in data and "human_plain_english_summary" in data, data
    print("verify_autopilot_decision_state_endpoint: PASS")
    print({"paths": ["/api/autonomous-paper-learning/decision-state", "/api/autopilot/decision-state"]})


if __name__ == "__main__":
    main()
