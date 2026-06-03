"""Phase 2 verifier: the latest bundle's current-run contract holds.

Asserts current-run order attempts / closed trades are shown SEPARATELY from historical orders /
outcomes, old orders cannot be mistaken for paper_validation_run_001, and system_summary does not
contradict validation_run / paper_order_proof (e.g. no "orders submitted 1" when current-run
attempts are 0).
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    with Session(engine) as w:
        build_latest_bundle(w, config={}); w.commit()
    b = build_latest_bundle(Session(engine), config={})

    assert "universe_summary.json" in b and "paper_validation_productivity.json" in b
    readme = b.get("README_FIRST.json") or {}
    for key in (
        "last_tick_at",
        "next_tick_at",
        "shadow_count",
        "why_no_trade",
        "paper_entry_ready",
        "paper_orders_enabled",
    ):
        assert key in readme, f"README_FIRST missing {key}"
    tt = b["current_run_trade_truth.json"]
    # Current-run vs historical are distinct fields.
    assert "current_run_order_attempts" in tt and "historical_orders_count" in tt
    assert "current_run_closed_trades" in tt and "historical_outcomes_count" in tt
    cur_attempts = int(tt.get("current_run_order_attempts") or 0)
    # Old orders cannot masquerade as current-run: historical counts are labeled historical + excluded.
    assert tt.get("historical_rows_excluded_from_latest") is True
    assert tt.get("validation_run_id"), "trade truth must carry the run id"

    # system_summary must not contradict the current-run truth (no "orders submitted N" when attempts=0).
    summ = str(b.get("system_summary.md") or "")
    if cur_attempts == 0:
        assert "submitted: 1" not in summ.lower() and "orders submitted 1" not in summ.lower(), "summary contradicts 0 attempts"
        assert f"current_run_order_attempts={cur_attempts}" in summ, "summary must state current-run attempts"

    print(f"verify_latest_bundle_current_run_contract: PASS (current-run attempts={cur_attempts} separate from historical; summary consistent)")


if __name__ == "__main__":
    main()
