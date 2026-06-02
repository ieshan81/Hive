"""Verify stock readiness requires FRESH bars — bars_returned > 0 is not enough.

A stale latest bar (e.g. the prod 2026-02-02 bar while the server clock is months ahead) must be
classified STOCK_BARS_STALE and blocked (readiness_status != ready, scanner_allowed False). Also
asserts the live scorer's bar-freshness gate marks stale bars non-executable.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# DB-free: stock_data_readiness_service imports the adapter lazily inside its main function.
from app.services.stock_data_readiness_service import BLOCKER_CODES, _classify, _freshness  # noqa: E402


def main() -> None:
    assert "STOCK_BARS_STALE" in BLOCKER_CODES, "STOCK_BARS_STALE blocker missing"
    now = datetime(2026, 6, 2, 16, 0, 0)
    fmt = lambda dt: dt.isoformat() + "+00:00"  # noqa: E731

    # --- freshness rule ---
    # Fresh during market hours: within the 30-min open window.
    st, age, mx = _freshness(fmt(now - timedelta(minutes=10)), now, True, 30, 5760)
    assert st == "fresh", f"recent open-market bar should be fresh, got {st}"
    # The exact prod bug: a ~120-day-old bar during open market is STALE.
    st, age, mx = _freshness("2026-02-02T20:40:00+00:00", now, True, 30, 5760)
    assert st == "stale" and age > 100000, f"120-day-old bar must be stale, got {st} age={age}"
    # Market closed: a last-session bar (2 days) is fresh; a 120-day bar is still stale.
    st, _, _ = _freshness(fmt(now - timedelta(days=2)), now, False, 30, 5760)
    assert st == "fresh", "last-session bar within closed tolerance should be fresh"
    st, _, _ = _freshness("2026-02-02T20:40:00+00:00", now, False, 30, 5760)
    assert st == "stale", "120-day-old bar must be stale even when market closed"
    # No bar -> unknown (not silently fresh).
    st, age, _ = _freshness(None, now, True, 30, 5760)
    assert st == "unknown" and age is None, "missing bar must be 'unknown', never fresh"

    # --- readiness gating logic mirrors the service (ready ONLY if bars>0 AND fresh) ---
    def ready(bars_n, freshness, err=None):
        code = _classify(bars_n, True, err, 2)
        if code is None and freshness == "stale":
            code = "STOCK_BARS_STALE"
        return code is None and bars_n > 0 and freshness == "fresh"

    assert ready(60, "fresh") is True, "fresh bars should be ready"
    assert ready(60, "stale") is False, "stale bars must NOT be ready (bars>0 is not enough)"
    assert ready(0, "unknown") is False, "no bars must not be ready"

    # --- the service actually wires this gate + the STALE override ---
    svc = (BACKEND / "app/services/stock_data_readiness_service.py").read_text(encoding="utf-8", errors="ignore")
    assert 'code = "STOCK_BARS_STALE"' in svc, "service does not override stale bars to STOCK_BARS_STALE"
    assert 'is_ready = code is None and bars_n > 0 and freshness == "fresh"' in svc, \
        "service readiness gate must require fresh bars"
    assert '"scanner_allowed": is_ready' in svc, "service must expose scanner_allowed tied to freshness"

    # --- live scorer's bar-freshness gate marks stale bars non-executable ---
    bf = (BACKEND / "app/services/bar_freshness_service.py").read_text(encoding="utf-8", errors="ignore")
    assert '"executable": fresh' in bf, "BarFreshnessService must tie executable to freshness"
    assert '"reason": "data_stale"' in bf or 'reason": None if fresh else "data_stale"' in bf, \
        "stale bars must carry a data_stale reason"
    print("verify_stock_readiness_requires_fresh_bars: PASS (stale bars blocked; ready requires fresh; scorer gates stale)")


if __name__ == "__main__":
    main()
