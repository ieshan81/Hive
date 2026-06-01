"""Near-max-hold should tighten/hold, not sell just because the clock is near max."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import PositionSnapshot
from app.services.open_position_review_service import OpenPositionReviewService


class _Spike:
    def __init__(self, *_args, **_kwargs):
        pass

    def evaluate_symbol(self, symbol: str) -> dict:
        return {"symbol": symbol, "suggested_action": "observe_only", "reason_codes": []}


def main() -> None:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as session:
        pos = PositionSnapshot(
            symbol="UNI/USD",
            qty=1,
            side="long",
            avg_entry_price=10,
            current_price=9.99,
            market_value=9.99,
            unrealized_pl=-0.01,
            unrealized_pl_pct=-0.1,
            synced_at=datetime.utcnow(),
        )
        session.add(pos)
        session.commit()
        cfg = {
            "crypto_push_pull": {"max_hold_hours": 0.5},
            "autonomous_paper_learning": {"max_unrealized_loss_usd": 4.0, "max_unrealized_loss_pct": 1.5},
        }
        with (
            patch("app.services.open_position_review_service.build_position_truth", lambda *_a, **_k: {"strategy_name": "crypto_push_pull_baseline"}),
            patch("app.services.open_position_review_service.resolve_entry_time", lambda *_a, **_k: {"true_hold_minutes": 27.0, "entry_time": (datetime.utcnow() - timedelta(minutes=27)).isoformat() + "Z"}),
            patch.object(OpenPositionReviewService, "_dynamic_levels", lambda *_a, **_k: None),
            patch.object(OpenPositionReviewService, "_strategy_intent", lambda *_a, **_k: "quick_push_pull"),
            patch("app.services.open_position_review_service.MemeVolatilitySpikeDetector", _Spike),
        ):
            out = OpenPositionReviewService(session, cfg).review_position("UNI/USD", pos)
    assert out["action"] in ("tighten_stop", "hold"), out
    assert out["action"] != "exit_recommended", out
    assert out["reason"] != "at_or_near_max_hold", out
    print("verify_no_near_max_hold_churn_exit: PASS")
    print({"action": out["action"], "reason": out["reason"]})


if __name__ == "__main__":
    main()
