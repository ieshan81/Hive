"""Every Alpaca submission path blocks non-paper broker URL."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.alpaca_adapter import AlpacaAdapter
from app.services import broker_safety


def main():
    init_db()
    with Session(engine) as session:
        adapter = AlpacaAdapter(session)
        with patch.object(broker_safety, "broker_base_url", return_value="https://api.alpaca.markets"):
            with patch.object(broker_safety, "is_paper_broker_url", return_value=False):
                ioc = adapter.submit_marketable_limit_ioc("DOGE/USD", 1, "buy", limit_price=0.1)
                paper = adapter.submit_paper_order("DOGE/USD", 1, "buy")
                cancel = adapter.cancel_order("fake-id")
        assert ioc.get("success") is False and ioc.get("error") == "BROKER_NOT_PAPER"
        assert paper.get("success") is False
        assert cancel.get("success") is False
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
