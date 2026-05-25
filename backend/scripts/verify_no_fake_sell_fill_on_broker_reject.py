"""Broker reject must not create filled sell OrderRecord."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, engine, init_db


def main():
    init_db()
    with Session(engine) as session:
        sells = session.exec(select(OrderRecord).where(OrderRecord.side == "sell", OrderRecord.status == "filled")).all()
        rejected = session.exec(
            select(ExecutionLog).where(ExecutionLog.status == "paper_order_rejected", ExecutionLog.side == "sell")
        ).all()
        for r in rejected:
            assert not any(s.alpaca_order_id == r.broker_order_id and s.status == "filled" for s in sells if r.broker_order_id)
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
