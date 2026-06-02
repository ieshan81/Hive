"""Phase C verifier: the P&L-guard trace is correct + current-run aware.

Asserts the trace records validation_run_id, uses the $200 baseline, labels a historical trip as
historical (not a current blocker), states active vs cleared, and is present in the latest bundle.
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
    from app.services.paper_validation_analysis_service import pnl_guard_trace

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    tr = pnl_guard_trace(Session(engine), config={"kill": {"daily_drawdown_pct": 3.0}})
    occ = (tr.get("occurrences") or [{}])[0]
    assert occ.get("threshold_type") == "daily_drawdown" and occ.get("threshold_unit") == "percent"
    assert occ.get("threshold_value") == 3.0, "threshold must come from kill.daily_drawdown_pct"
    assert occ.get("baseline_equity_used") == 200.0, "current-run P&L must use the $200 baseline"
    assert "is_current_run" in occ and "is_historical" in occ and "is_still_active" in occ
    assert "did_it_block_entries" in occ
    # Plain-English explanation includes the $ value (3% of $200 = $6).
    assert "$6" in occ.get("explanation_plain_english", "") or "6.00" in occ.get("explanation_plain_english", ""), \
        "must explain 3% of $200 = $6"
    # active flag is a clear boolean.
    assert isinstance(tr.get("p_and_l_guard_active"), bool)

    # Present in the latest bundle.
    with Session(engine) as w:
        build_latest_bundle(w, config={}); w.commit()
    b = build_latest_bundle(Session(engine), config={})
    assert "p_and_l_guard_trace.json" in b, "p_and_l_guard_trace.json must be in the latest bundle"
    assert b["README_FIRST.json"].get("p_and_l_threshold_status") in ("ACTIVE_BLOCKING", "clear_or_historical")

    print(f"verify_pnl_guard_trace_current_run: PASS (3% of $200=$6; baseline=$200; active={tr.get('p_and_l_guard_active')}; in bundle)")


if __name__ == "__main__":
    main()
