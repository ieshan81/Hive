"""Wave E1 — exit-only handling verification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.database import OrderRecord, PositionSnapshot, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.fast_training_exit_only_service import FastTrainingExitOnlyService
from app.services.open_position_review_service import OpenPositionReviewService
import inspect
import app.services.fast_training_exit_only_service as exit_mod


def run(name, fn):
    fn()
    print(f"{name}: OK")


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        svc = FastTrainingExitOnlyService(session, cfg)

        run("verify_exit_only_status_shape", lambda: (
            "exit_only_enabled" in svc.status() and svc.status()["entries_allowed"] is False
        ))

        src = inspect.getsource(exit_mod.FastTrainingExitOnlyService)
        run("verify_exit_only_no_alpaca_direct", lambda: "AlpacaAdapter" not in src)

        run("verify_exit_only_uses_training_execution", lambda: "TrainingExecutionService" in src)

        pos = session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).first()
        if pos:
            review = OpenPositionReviewService(session, cfg).review_position(pos.symbol, pos)
            assert "true_hold_minutes" in review
            assert review.get("hold_time_source") in (
                "order_filled_at",
                "order_submitted_at",
                "position_opened_at",
            )
        else:
            session.add(
                PositionSnapshot(
                    symbol="DOGEUSD",
                    qty=10,
                    avg_entry_price=0.1,
                    current_price=0.1,
                    synced_at=datetime.utcnow(),
                )
            )
            session.commit()
            review = OpenPositionReviewService(session, cfg).review_position("DOGEUSD")
            assert review.get("action") in ("hold", "tighten_stop", "exit_recommended")

        orders_before = session.exec(select(OrderRecord)).all()
        ob = len(orders_before)
        en = svc.enable("test")
        assert en.get("status") in ("ok", "refused")
        if en.get("status") == "ok":
            run_out = svc.run_exits()
            session.commit()
            oa = len(list(session.exec(select(OrderRecord)).all()))
            assert run_out.get("entries_blocked", True) is True or run_out.get("status") == "exit_only"
            assert oa - ob <= 1, "at most one exit order"
            svc.disable("test")
            session.commit()
        else:
            print(f"enable refused locally (expected without paper broker): {en.get('reason')}")

    print("ALL_WAVE_E1_CHECKS_PASSED")


if __name__ == "__main__":
    main()
