"""Verify shadow league status exposes runtime fields and broker_evidence_count=0."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REQUIRED = (
    "scheduler_seen",
    "scheduler_enabled",
    "reason_shadow_count_zero",
    "broker_evidence_count",
    "total_shadow_observations",
    "total_shadow_trades",
    "closest_setup",
)


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.shadow_league_status_service import build_shadow_league_status

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        st = build_shadow_league_status(session, {})
        assert st.get("enabled") is True
        missing = [k for k in REQUIRED if k not in st]
        assert not missing, missing
        assert st.get("broker_evidence_count") == 0
        assert st.get("counts_as_broker_evidence") is False
    print("verify_shadow_league_runtime_enabled: PASS")


if __name__ == "__main__":
    main()
