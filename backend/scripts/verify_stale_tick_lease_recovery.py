"""Stale scheduler tick lease must recover safely on status read."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import FastTrainingLease, engine
    from app.services.fast_training_lease_service import FastTrainingLeaseService, SCHEDULER_TICK_LEASE_KEY

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        svc = FastTrainingLeaseService(session, lease_key=SCHEDULER_TICK_LEASE_KEY, ttl_seconds=60)
        row = svc._row()
        row.holder_id = "stale-test-holder"
        row.acquired_at = datetime.utcnow() - timedelta(minutes=10)
        row.expires_at = datetime.utcnow() - timedelta(minutes=5)
        session.add(row)
        session.commit()

        st = svc.status()
        assert st.get("lease_held") is False, st
        assert st.get("lease_stale_cleared") is True, st

        row2 = session.get(FastTrainingLease, SCHEDULER_TICK_LEASE_KEY)
        assert row2 is not None
        assert row2.holder_id is None, row2.holder_id

    print("verify_stale_tick_lease_recovery: PASS")


if __name__ == "__main__":
    main()
