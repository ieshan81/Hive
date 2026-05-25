"""Strategy import blocks path traversal outside sandbox."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.strategy_import_service import StrategyImportService


def main():
    init_db()
    with Session(engine) as session:
        svc = StrategyImportService(session)
        bad = svc.import_file("/etc/passwd")
        assert bad["status"] == "error"
        assert "not allowed" in bad["message"].lower() or "sandbox" in bad["message"].lower()
        bad2 = svc.import_file("../../../backend/.env")
        assert bad2["status"] == "error"
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
