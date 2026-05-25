"""Wave F — strategy import sandbox."""

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
        st = svc.status()
        assert st.get("broker_access") is False
        assert st.get("network") is False
        bad = svc.import_manifest(
            {"strategy_id": "bad_py", "name": "Bad"},
            python_source="import os\nos.environ['x']=1",
        )
        assert bad.get("status") == "error"
        ok = svc.import_manifest(
            {"strategy_id": "sandbox_ok", "name": "Sandbox OK", "symbols": ["DOGE/USD"]},
            python_source="import math\ndef signal():\n return 1",
        )
        assert ok.get("status") == "ok"
        session.commit()
    print("ALL_WAVE_F_CHECKS_PASSED")


if __name__ == "__main__":
    main()
