from datetime import datetime, timedelta, UTC
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, SQLModel, create_engine

from app.database import HistoricalBar
from app.services.bar_freshness_service import BarFreshnessService
from app.services.universe_strategy_discovery_service import _db_bars_only


def main() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            HistoricalBar(
                symbol="BTCUSD",
                asset_class="crypto",
                timeframe="5Min",
                timestamp=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1.0,
            )
        )
        session.commit()

        freshness = BarFreshnessService(session, {}).check_db_only("BTC/USD", "5Min")
        assert freshness["fresh"] is True, freshness
        assert freshness["meta"]["matched_symbol"] == "BTCUSD", freshness

        bars = _db_bars_only(session, "BTC/USD", "5Min", 10)
        assert len(bars) == 1, bars
        assert bars[0]["close"] == 100.5, bars

    print("verify_universe_symbol_freshness_variants: PASS")


if __name__ == "__main__":
    main()
