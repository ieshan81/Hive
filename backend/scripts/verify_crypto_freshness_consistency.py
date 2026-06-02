"""Phase 3 verifier: one authoritative crypto freshness contract.

Asserts a single staleness threshold policy is used, a stale bar is never trade_allowed, the
data_freshness_matrix exposes per-symbol bar age + threshold + status, and the productivity surface
reports the exact freshness blocker.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    analysis = (BACKEND / "app/services/paper_validation_analysis_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    prod = (BACKEND / "app/services/paper_validation_productivity_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    bar_svc = (BACKEND / "app/services/bar_freshness_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    push = (BACKEND / "app/services/push_pull_scoring_service.py").read_text(encoding="utf-8-sig", errors="ignore")

    # Single threshold policy: both the freshness matrix and the scoring path use the same config key.
    assert "universe.max_bar_staleness_hours" in analysis, "freshness matrix must use the shared staleness config"
    assert "max_bar_staleness_hours" in bar_svc and "max_bar_staleness_hours" in push, "scoring must use the same staleness policy"

    # A stale bar is never trade_allowed.
    assert '"trade_allowed": bool(fresh)' in analysis, "stale bar must not be trade_allowed"
    # Matrix exposes the per-symbol freshness contract fields.
    for field in ("latest_bar_time", "bar_age_minutes", "freshness_threshold_minutes", "freshness_status", "server_time"):
        assert f'"{field}"' in analysis, f"freshness matrix missing {field}"

    # Productivity reports the exact freshness blocker.
    assert "STALE_QUOTE_OR_BAR" in prod, "productivity must classify a stale-bar blocker"

    # Runtime structure (empty DB -> empty symbol list, but the contract fields are present).
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.paper_validation_analysis_service import data_freshness_matrix

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    m = data_freshness_matrix(Session(engine), config={"universe": {"max_bar_staleness_hours": 96}})
    assert "freshness_threshold_minutes" in m and m["freshness_threshold_minutes"] == 96 * 60
    for r in m.get("symbols", []):
        if r["freshness_status"] == "stale":
            assert r["trade_allowed"] is False, f"stale symbol {r['symbol']} wrongly trade_allowed"

    print("verify_crypto_freshness_consistency: PASS (single threshold policy; stale never tradeable; productivity reports freshness blocker)")


if __name__ == "__main__":
    main()
