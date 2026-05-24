import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.positions_tab_service import current_positions, orders_history, trades_history
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        pos = current_positions(session)
        orders = orders_history(session, limit=5)
        trades = trades_history(session, limit=5)
        assert isinstance(pos, list)
        assert isinstance(orders, list)
        assert isinstance(trades, list)
        print("verify_positions_tab_data: PASS")


if __name__ == "__main__":
    test()
