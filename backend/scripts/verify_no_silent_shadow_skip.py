"""Zero-shadow ticks must record an exact measurable reason code."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.shadow_tick_diagnostics import classify_zero_shadow_tick_reason  # noqa: E402

ALLOWED = {
    "no_rows_scored",
    "quality_below_observation_floor",
    "data_stale",
    "shadow_disabled",
    "write_failed",
    "validation_run_missing",
    "exception",
}


def main() -> None:
    cases = [
        dict(rows_scored=0, rows_above_observation_floor=0, shadow_observations_created=0, shadow_errors=0, shadow_disabled=False, validation_run_missing=False, expect="no_rows_scored"),
        dict(rows_scored=5, rows_above_observation_floor=0, shadow_observations_created=0, shadow_errors=0, shadow_disabled=False, validation_run_missing=False, expect="quality_below_observation_floor"),
        dict(rows_scored=5, rows_above_observation_floor=2, shadow_observations_created=0, shadow_errors=0, shadow_disabled=False, validation_run_missing=False, expect="write_failed"),
        dict(rows_scored=1, rows_above_observation_floor=1, shadow_observations_created=0, shadow_errors=2, shadow_disabled=False, validation_run_missing=False, expect="exception"),
        dict(rows_scored=0, rows_above_observation_floor=0, shadow_observations_created=0, shadow_errors=0, shadow_disabled=True, validation_run_missing=False, expect="shadow_disabled"),
        dict(rows_scored=0, rows_above_observation_floor=0, shadow_observations_created=0, shadow_errors=0, shadow_disabled=False, validation_run_missing=True, expect="validation_run_missing"),
    ]
    for c in cases:
        expect = c.pop("expect")
        got = classify_zero_shadow_tick_reason(**c)
        assert got == expect, (c, got)
        assert got in ALLOWED, got
    print("verify_no_silent_shadow_skip: PASS")


if __name__ == "__main__":
    main()
