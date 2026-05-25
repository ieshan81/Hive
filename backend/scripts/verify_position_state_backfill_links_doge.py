"""Verify DOGE position state links signal 38 after backfill."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine, OrderRecord, PositionSnapshot
from sqlmodel import Session, select
from app.services.position_state_service import backfill_position_states


def main():
    init_db()
    with Session(engine) as session:
        orders = session.exec(select(OrderRecord)).all()
        if not orders:
            print("SKIP: no orders in DB — seed or run against Railway DB")
            return
        out = backfill_position_states(session)
        session.commit()
        doge = next((s for s in out["states"] if "DOGE" in str(s.get("broker_symbol", "")).upper()), None)
        assert doge, f"no DOGE state in {out}"
        assert doge.get("signal_id") == 38, f"signal_id={doge.get('signal_id')}"
        assert doge.get("cycle_run_id") == "8796825e-5f25-4cfa-b0f9-b0141f61859c"
        assert doge.get("strategy_name") == "crypto_push_pull"
        assert doge.get("stop_loss") is not None
        assert doge.get("take_profit") is not None
        print("verify_position_state_backfill_links_doge: OK", doge.get("signal_id"), doge.get("strategy_name"))


if __name__ == "__main__":
    main()
