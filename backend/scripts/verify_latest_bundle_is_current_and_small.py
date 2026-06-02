"""Phase D verifier: the default (latest) bundle is current-run, small, and analysis-first.

Asserts the bundle is not forensic, under the file-count + size caps, includes the analysis-first
files, keeps current_run_order_attempts separate from historical_orders_count, carries
validation_run_id in major files, and never dumps full raw old orders/trades/outcomes.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

REQUIRED = [
    "README_FIRST.json", "system_summary.md", "paper_validation_productivity.json",
    "current_run_trade_truth.json", "p_and_l_guard_trace.json", "universe_summary.json",
    "data_freshness_matrix.json", "alpha_coverage_matrix.json", "blocker_timeline.json",
    "changed_since_previous_bundle.json", "endpoint_latency_summary.json",
    "validation_run.json", "hive_engine_map.json", "memory_governance_summary.json",
]
# Full raw history files that must NOT be in the latest bundle.
FORBIDDEN = ["orders.json", "trades.json", "closed_trade_outcomes.json", "backtest_runs.json",
             "activity.json", "lesson_nodes.json", "ai_memories.json"]


def main() -> None:
    import json

    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.config import settings
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    # Seed a reset epoch so the bundle reflects an ACTIVE validation run (as in prod).
    from app.services.nuke_epoch_service import PAPER_BASELINE_EQUITY, PAPER_VALIDATION_RUN_ID, record_reset_epoch
    with Session(engine) as s:
        record_reset_epoch(s, "verifier", deleted={}, validation_run_id=PAPER_VALIDATION_RUN_ID,
                           baseline_equity=PAPER_BASELINE_EQUITY)
        s.commit()
    with Session(engine) as w:  # warm lazy singletons
        build_latest_bundle(w, config={}); w.commit()
    b = build_latest_bundle(Session(engine), config={})

    assert b["bundle_meta.json"]["bundle_mode"] == "latest", "default bundle must be latest, not forensic"
    cap_files = 40
    assert len(b) <= cap_files, f"latest bundle has {len(b)} files (> {cap_files} cap)"
    size_mb = len(json.dumps(b, default=str)) / (1024 * 1024)
    cap_mb = int(getattr(settings, "diagnostic_max_default_bundle_mb", 10) or 10)
    assert size_mb < cap_mb, f"latest bundle {size_mb:.2f}MB exceeds {cap_mb}MB"

    for f in REQUIRED:
        assert f in b, f"latest bundle missing analysis file {f}"
    for f in FORBIDDEN:
        assert f not in b, f"latest bundle dumps full-history file {f}"

    tt = b["current_run_trade_truth.json"]
    assert "current_run_order_attempts" in tt and "historical_orders_count" in tt, "must separate current vs historical orders"
    assert tt.get("historical_rows_excluded_from_latest") is True
    rd = b["README_FIRST.json"]
    assert rd.get("current_run_order_attempts") is not None or rd.get("current_run_order_attempts") == 0
    for major in ("README_FIRST.json", "validation_run.json", "current_run_trade_truth.json"):
        v = b[major]
        assert isinstance(v, dict) and (v.get("validation_run_id") or v.get("current_validation_run_id")), f"{major} missing validation_run_id"

    # Contract: building the JSON view is read-pure (no snapshot written); downloading the ZIP writes
    # exactly one baseline snapshot used by changed_since_previous_bundle.json next time.
    from app.database import SettingsActionAudit
    from app.services.diagnostic_bundle_latest import latest_bundle_as_zip
    from app.services.paper_validation_analysis_service import HEADLINE_SNAPSHOT_ACTION

    def _snap_count():
        return _count_action(engine, SettingsActionAudit, HEADLINE_SNAPSHOT_ACTION)

    before = _snap_count()
    build_latest_bundle(Session(engine), config={})  # JSON view -> must NOT write
    assert _snap_count() == before, "JSON bundle build must be read-pure (wrote a snapshot)"
    z = latest_bundle_as_zip(Session(engine), config={})  # download -> writes exactly one
    assert isinstance(z, (bytes, bytearray)) and len(z) > 0, "zip download must produce bytes"
    assert _snap_count() == before + 1, "ZIP download must record exactly one headline snapshot"
    cb = b["changed_since_previous_bundle.json"]
    assert "previous_snapshot_available" in cb and "current_headline" in cb and "changes" in cb

    print(f"verify_latest_bundle_is_current_and_small: PASS ({len(b)} files, {size_mb*1024:.0f}KB; analysis files present; current!=historical; read-pure JSON / snapshot-on-download)")


def _count_action(engine, model, action) -> int:
    from sqlmodel import Session, func, select
    with Session(engine) as s:
        try:
            return int(s.exec(select(func.count()).select_from(model).where(model.action == action)).one() or 0)
        except Exception:
            return 0


if __name__ == "__main__":
    main()
