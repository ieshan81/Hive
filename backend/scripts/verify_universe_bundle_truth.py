"""Phase 5 verifier: the latest diagnostic bundle carries universe fast-path truth.

Asserts the default (latest) bundle includes universe_summary.json with source proof + funnel, the
README_FIRST carries universe current truth (display/cached/fresh/eligible/shortlist + latency risk),
the current validation_run_id is present, and slow /status is never treated as false-zero truth.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    src = (BACKEND / "app/services/diagnostic_bundle_latest.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert '"universe_summary.json": universe' in src, "latest bundle must include universe_summary.json"
    assert '"universe_truth"' in src, "README_FIRST must include universe_truth"

    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    b = build_latest_bundle(Session(engine), config={})

    assert "universe_summary.json" in b, "bundle missing universe_summary.json"
    us = b["universe_summary.json"]
    assert isinstance(us, dict) and us.get("endpoint_kind") == "fast_path", "universe summary must be the fast path"
    assert "source_counts" in us and "funnel_counts" in us, "universe summary must carry source + funnel layers"

    readme = b["README_FIRST.json"]
    assert "current_validation_run_id" in readme and readme.get("includes_historical_rows") is False
    ut = readme.get("universe_truth") or {}
    for k in ("universe_display_total", "universe_cached", "universe_fresh", "universe_eligible",
              "universe_execution_shortlist", "universe_status_timeout_risk", "universe_ui_truth_status"):
        assert k in ut, f"README universe_truth missing {k}"
    # Source proof present (curated source is always non-zero); display total non-zero.
    assert (ut.get("universe_display_total") or 0) > 0, "universe display total must be non-zero in README"
    assert "summary" in str(ut.get("universe_ui_truth_status")).lower(), "README must steer reader to the fast summary"

    print("verify_universe_bundle_truth: PASS (latest bundle has universe fast-path + README universe truth; run id present)")


if __name__ == "__main__":
    main()
