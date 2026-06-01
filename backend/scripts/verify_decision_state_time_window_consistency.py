"""Decision state must not confuse latest historical sell with latest tick decision."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import ExecutionLog, OrderRecord, SettingsActionAudit
from app.services.autopilot_decision_state_service import AutopilotDecisionStateService
from app.services.exposure_truth_service import ExposureTruthService


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    original = ExposureTruthService.fresh_broker_positions
    ExposureTruthService.fresh_broker_positions = lambda self: ([], True, {"source": "fixture_fresh_broker_flat"})
    try:
        with Session(eng) as session:
            session.add(
                SettingsActionAudit(
                    action="autonomous_run_one_cycle",
                    details_json={
                        "orders_created": 0,
                        "reason": "preflight_blocked",
                        "selected_candidate": {"symbol": "UNI/USD", "entry_allowed": True},
                    },
                )
            )
            session.add(OrderRecord(symbol="UNI/USD", side="sell", qty=1, status="filled", filled_at=datetime.utcnow()))
            session.add(
                ExecutionLog(
                    event_id="hist-sell",
                    cycle_run_id="old",
                    symbol="UNI/USD",
                    side="sell",
                    status="paper_order_filled",
                    reject_reason=None,
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()
            out = AutopilotDecisionStateService(session).state()
    finally:
        ExposureTruthService.fresh_broker_positions = original
    assert out["tick_selected_candidate"]["symbol"] == "UNI/USD", out
    assert out["last_order"]["side"] == "sell", out
    assert out["final_trade_decision"] == "approved_pending_or_blocked", out
    assert out["final_trade_decision"] != "no_trade", out
    print("verify_decision_state_time_window_consistency: PASS")
    print({"final_trade_decision": out["final_trade_decision"], "last_order_side": out["last_order"]["side"]})


if __name__ == "__main__":
    main()
