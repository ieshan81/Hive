"""Release a stuck scheduler_tick DB lease (operator maintenance only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session

    from app.database import engine
    from app.services.fast_training_lease_service import (
        SCHEDULER_TICK_LEASE_KEY,
        FastTrainingLeaseService,
    )

    with Session(engine) as session:
        svc = FastTrainingLeaseService(session, lease_key=SCHEDULER_TICK_LEASE_KEY)
        before = svc.status()
        row = svc._row()
        row.holder_id = None
        row.acquired_at = None
        row.expires_at = None
        session.add(row)
        session.commit()
        after = svc.status()
        print(
            f"release_scheduler_tick_lease: before_held={before.get('lease_held')} "
            f"after_held={after.get('lease_held')}"
        )


if __name__ == "__main__":
    main()
