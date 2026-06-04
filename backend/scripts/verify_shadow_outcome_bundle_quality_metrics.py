"""Latest bundle must expose shadow outcome quality aggregates."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REQUIRED = (
    "open_count",
    "closed_count",
    "wins",
    "losses",
    "avg_pnl_bps",
    "median_pnl_bps",
    "zero_pnl_closed_count",
    "instant_close_count",
    "close_reason_counts",
)


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        bundle = build_latest_bundle(session)
        q = bundle.get("shadow_outcome_quality.json") or {}
        missing = [k for k in REQUIRED if k not in q]
        assert not missing, missing
        assert q.get("counts_as_broker_evidence") is False
        assert q.get("broker_orders_from_shadow") == 0
    print("verify_shadow_outcome_bundle_quality_metrics: PASS")


if __name__ == "__main__":
    main()
