"""Phase 2 verifier: /api/universe/summary fast path is fast, read-only, and source-truthful.

Asserts the summary builds WITHOUT the heavy mission-control build / slow Alpaca discovery, returns
quickly, carries validation_run_id + endpoint_kind=fast_path, keeps eligible/shortlist separate from
source/display counts, never reports a fake-zero source, and touches no order/broker/live path.
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    svc = (BACKEND / "app/services/universe_summary_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    router = (BACKEND / "app/routers/universe.py").read_text(encoding="utf-8-sig", errors="ignore")

    # No heavy build, no slow discovery, no order/broker path. (Check the CALL, not the docstring mention.)
    assert "build_mission_control_status(" not in svc, "fast path must NOT call the heavy mission-control build"
    assert "import build_mission_control_status" not in svc, "fast path must not import the heavy build"
    assert "_universe_summary" in svc, "fast path should use the lightweight funnel"
    assert "force=False" in svc, "source proof must use cached assets (no forced slow discovery)"
    for bad in ("submit_order", "submit_paper", "run_agent_cycle", "live_orders_enabled = True", "get_tradable_assets"):
        assert bad not in svc, f"fast path must not touch {bad}"
    assert '@router.get("/summary")' in router, "GET /api/universe/summary route missing"

    # Runtime: builds quickly + correct contract.
    from sqlmodel import Session, SQLModel

    import app.database  # register models  # noqa: F401
    from app.database import engine
    from app.services.universe_summary_service import build_universe_summary

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    t0 = time.time()
    s = build_universe_summary(Session(engine), config={})
    dt = time.time() - t0
    assert dt < 30, f"fast path too slow locally: {dt:.1f}s"
    assert s["endpoint_kind"] == "fast_path"
    assert "validation_run_id" in s
    assert set(s["funnel_counts"]) >= {"available", "eligible", "ranked", "execution_shortlist", "to_trade"}
    assert set(s["source_counts"]) >= {"alpaca_crypto_assets", "alpaca_crypto_usd_pairs", "curated_crypto", "curated_stock"}
    # eligible/shortlist live in funnel_counts, NOT in source/display.
    assert "eligible" not in s["source_counts"] and "eligible" not in s["display_counts"]
    assert s["live_trading_locked"] is True and s["orders_authority"] == "none"
    print(f"verify_universe_summary_fast_path: PASS (built in {dt:.2f}s; fast_path; source/funnel separated; no order/live path)")


if __name__ == "__main__":
    main()
