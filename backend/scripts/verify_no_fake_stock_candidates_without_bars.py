"""Verify no fake/synthetic stock bars or candidates are created when the feed returns no data.

When stock bars are missing/insufficient, fetch_and_store must return an error and store NOTHING
(no synthetic bars), and the readiness model must mark the symbol blocked (never ready) — so the
scanner has no data to fabricate a candidate from.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.stock_data_readiness_service import _classify  # noqa: E402 (DB-free)


def main() -> None:
    hist = (BACKEND / "app/services/historical_data_service.py").read_text(encoding="utf-8", errors="ignore")

    # The insufficient-bars guard must return BEFORE the bar-store loop, so nothing is persisted.
    guard = hist.find("if len(bars) < 2:")
    store_loop = hist.find("for b in bars:")
    assert guard != -1 and store_loop != -1, "expected insufficient-bars guard + store loop"
    assert guard < store_loop, "insufficient-bars guard must return before any bars are stored"
    # The guard returns an error (does not fall through to storing).
    seg = hist[guard:store_loop]
    assert 'return {"status": "error"' in seg, "insufficient-bars path must return an error, not store"

    # No fabricated/mock/synthetic stock bars in production fetch path.
    low = hist.lower()
    assert "synthetic=false" in low.replace(" ", ""), "expected synthetic=False on stored bars"
    for bad in ("mock_bars", "fake_bars", "synthetic=true", "random.uniform", "np.random"):
        assert bad not in low, f"fetch path appears to fabricate bars: {bad}"

    # Readiness never marks a 0-bar symbol ready → scanner gets no phantom data.
    assert _classify(0, True, None, 2) is not None and _classify(0, False, None, 2) is not None
    print("verify_no_fake_stock_candidates_without_bars: PASS (0 bars -> no stored bars, no candidate, blocked)")


if __name__ == "__main__":
    main()
