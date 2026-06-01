"""Real broker exposure still blocks duplicate paper buys."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.services.exposure_truth_service import ExposureTruthService


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        dupe = ExposureTruthService(session).duplicate_buy_decision(
            "LTC/USD",
            broker_positions=[{"symbol": "LTC/USD", "qty": 2.5, "market_value": 250}],
            broker_truth_available=True,
        )
    assert dupe["blocked"] is True, dupe
    assert dupe["reason"] == "broker_position_exists", dupe
    assert dupe["effective_exposure_state"] == "broker_open", dupe
    print("verify_duplicate_buy_blocks_real_broker_position: PASS")
    print({"symbol": "LTC/USD", "broker_qty": dupe["broker_qty"], "reason": dupe["reason"]})


if __name__ == "__main__":
    main()
