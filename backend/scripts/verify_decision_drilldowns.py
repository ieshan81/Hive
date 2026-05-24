import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine
from app.services.decisions_service import latest_summary
from sqlmodel import Session


def test():
    init_db()
    with Session(engine) as session:
        s = latest_summary(session, "latest")
        assert "counts" in s
        assert "approved" in s
        assert "blocked" in s
        print("verify_decision_drilldowns: PASS")


if __name__ == "__main__":
    test()
