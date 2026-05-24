import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import HistoricalBar, init_db, engine
from sqlmodel import Session, select


def main():
    init_db()
    with Session(engine) as session:
        synth = session.exec(select(HistoricalBar).where(HistoricalBar.synthetic == True)).all()  # noqa: E712
        assert len(synth) == 0, "no synthetic bars should exist by default"
        print("verify_backtest_no_fake_data: OK")


if __name__ == "__main__":
    main()
