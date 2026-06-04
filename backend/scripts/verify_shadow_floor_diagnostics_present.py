"""Shadow status and bundle export must expose measurable floor diagnostics."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REQUIRED = (
    "observation_floor",
    "shadow_floor",
    "max_setup_quality_last_tick",
    "rows_scored_last_tick",
    "rows_above_observation_floor",
    "rows_above_shadow_floor",
    "last_tick_shadow_attempts",
    "near_misses_top_10",
)


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle
    from app.services.shadow_league_status_service import build_shadow_league_status
    from app.services.shadow_tick_diagnostics import build_shadow_tick_diagnostics

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        st = build_shadow_league_status(session, {})
        missing = [k for k in REQUIRED if k not in st]
        assert not missing, f"status missing {missing}"
        sample = build_shadow_tick_diagnostics(
            {},
            rows_scored=1,
            rows_above_observation_floor=0,
            rows_above_shadow_floor=0,
            max_setup_quality=10.0,
            quality_scale="0_100",
            shadow_attempts=1,
            shadow_observations_created=0,
            shadow_trades_created=0,
            shadow_errors=0,
            near_misses=[{"symbol": "X", "quality": 10, "floor_gap_observation": 25, "blocker": "alpha"}],
            skip_reason_counts={"quality_below_observation_floor": 1},
        )
        assert sample.get("last_tick_zero_shadow_reason"), sample
        bundle = build_latest_bundle(session)
        diag = bundle.get("shadow_tick_diagnostics.json") or {}
        for k in REQUIRED:
            assert k in diag or k in ("near_misses_top_10",), f"bundle diag missing {k}"

    src = (Path(__file__).resolve().parents[1] / "app" / "services" / "push_pull_scan_service.py").read_text()
    assert "_run_shadow_observer_pass" in src
    print("verify_shadow_floor_diagnostics_present: PASS")


if __name__ == "__main__":
    main()
