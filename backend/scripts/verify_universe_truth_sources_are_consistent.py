"""Phase 1 verifier: Universe truth sources are consistent (no false zero).

Asserts the universe summary keeps source / display / freshness / funnel counts as SEPARATE layers,
never reports a plain 0 for an unknown source (uses null), and that a strict eligible=0 does not
imply a zero source universe. The UI contract therefore cannot render a false zero without a
stale/unknown label.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    svc = (BACKEND / "app/services/universe_summary_service.py").read_text(encoding="utf-8-sig", errors="ignore")

    # Separate layers exist (UI contract has source/display/freshness/funnel distinctly).
    for key in ("source_counts", "display_counts", "freshness_counts", "funnel_counts",
                "zero_eligible_explanation", "source_nonzero_but_eligible_zero", "status_latency_risk"):
        assert f'"{key}"' in svc, f"universe summary missing {key}"

    # Unknown source -> null, never a fake 0.
    assert "if has_crypto else None" in svc, "unknown Alpaca source must be null, not 0"

    # Runtime build (sqlite; funnel degrades safely). Source curated counts are real (>0),
    # funnel may be null/0 — and that must NOT zero out the source.
    from sqlmodel import Session, SQLModel

    import app.database  # register models  # noqa: F401
    from app.database import engine
    from app.services.universe_summary_service import build_universe_summary

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    s = build_universe_summary(Session(engine), config={})
    src = s["source_counts"]
    disp = s["display_counts"]
    fun = s["funnel_counts"]
    # Source/display layers are distinct objects from the funnel layer.
    assert set(src) != set(fun) and set(disp) != set(fun), "source/display must be distinct from funnel"
    # Curated source/display are genuinely non-zero (the bot can always see its watchlist).
    assert src["curated_crypto"] > 0 and src["curated_stock"] > 0, "curated source counts must be > 0"
    assert disp["total"] == disp["crypto"] + disp["stock"] and disp["total"] > 0, "display universe must be non-zero"
    # Unknown Alpaca crypto source is null (not 0) when the cache is empty.
    assert src["alpaca_crypto_assets"] is None or src["alpaca_crypto_assets"] > 0, "Alpaca source must be null or >0, never fake 0"
    assert src["alpaca_stock_assets"] is None, "stock source is unknown on fast path -> null"
    # eligible=0 must not imply source=0.
    if (fun.get("eligible") or 0) == 0:
        assert (src["curated_crypto"] + src["curated_stock"]) > 0, "eligible=0 wrongly implied zero source"
    assert s["live_trading_locked"] is True and s["orders_authority"] == "none"
    print("verify_universe_truth_sources_are_consistent: PASS (source/display/funnel separated; unknown->null; eligible!=source)")


if __name__ == "__main__":
    main()
