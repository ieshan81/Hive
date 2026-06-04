"""Latest bundle must include shadow_tick_diagnostics with evidence, not vague-only text."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
        assert "shadow_tick_diagnostics.json" in bundle, bundle.keys()
        diag = bundle["shadow_tick_diagnostics.json"]
        assert "observation_floor" in diag, diag
        assert "rows_scored_last_tick" in diag, diag
        assert "near_misses_top_10" in diag, diag
        meta = bundle.get("bundle_meta.json") or {}
        errs = meta.get("section_errors") or []
        assert not any(
            isinstance(e, dict) and e.get("section") == "shadow_bundle" and e.get("error") == "timeout"
            for e in errs
        ), errs
        assert diag.get("observation_floor") is not None
        assert "push_pull_shadow_observer_ran" in diag or diag.get("quality_scale")
        assert diag.get("reason_shadow_count_zero") != "no_eligible_setups_met_observation_floor" or diag.get(
            "rows_scored_last_tick"
        ) is not None
    print("verify_latest_bundle_shadow_diagnostics: PASS")


if __name__ == "__main__":
    main()
