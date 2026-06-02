"""Phase 12 verifier: paper-validation productivity truth is honest + read-only.

Asserts a zero-candidate state always carries an exact reason, the surface never claims "nothing
scanned" when symbols were scanned, never claims "ready" when a blocker exists, and touches no
order/live path.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    svc = (BACKEND / "app/services/paper_validation_productivity_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    # Read-only: no order/broker/live mutation in the productivity surface.
    for bad in ("submit_order", "submit_paper", ".enable(", "run_agent_cycle", "live_orders_enabled = True"):
        assert bad not in svc, f"productivity surface must not touch {bad}"
    assert '"orders_authority": "none"' in svc and '"live_trading_locked": True' in svc

    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.paper_validation_productivity_service import build_productivity

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    p = build_productivity(Session(engine), config={})

    # Zero candidates -> an exact reason is always present.
    if int(p.get("paper_candidates") or 0) == 0:
        assert p.get("zero_candidate_reason"), "zero candidates must carry an exact reason"
        assert p.get("missing_evidence"), "zero candidates must state missing evidence"
    # No false 'nothing scanned' if symbols were scanned.
    if int(p.get("symbols_scanned") or 0) > 0:
        assert p.get("zero_candidate_reason") != "NO_DATA_NO_SCAN", "scanned symbols wrongly reported as no-scan"
    # Engine state is one of the known honest states (never a bare 'ready').
    assert p.get("engine_state") in ("watching", "waiting_for_scan", "evaluating_candidates", "degraded")
    # Blocked breakdown + read-only markers present.
    assert "blocked_breakdown" in p and "exact_next_blocker" in p
    assert p.get("live_trading_locked") is True and p.get("orders_authority") == "none"

    print(f"verify_paper_validation_productivity_truth: PASS (engine={p.get('engine_state')}, "
          f"zero_reason={p.get('zero_candidate_reason')}; read-only, no order/live path)")


if __name__ == "__main__":
    main()
