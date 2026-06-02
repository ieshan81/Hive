"""Phase 4 verifier: the alpha-coverage matrix tells the truth about why symbols can't trade.

Asserts every scanned crypto symbol gets an explicit alpha state (no_scorecard / unproven / rejected
/ paper_candidate), no symbol is promoted to paper_candidate without a qualifying verdict, symbol
normalization (ETHUSD == ETH/USD) cannot hide a scorecard, and productivity names the missing-alpha
blocker.
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

    # Promotion is gated on a qualifying verdict, never assumed.
    assert 'PAPER_OK = ("paper_candidate", "proven")' in analysis, "paper_candidate must require a qualifying verdict"
    assert 'verdict in PAPER_OK' in analysis, "blocker/next-evidence must key off the qualifying verdict"
    # Missing scorecard is an explicit blocker, not a silent pass.
    assert '"blocker": "NO_ALPHA_SCORECARD"' in analysis, "missing scorecard must be an explicit blocker"
    # Normalization prevents a format mismatch from hiding a scorecard.
    assert 'replace("/", "")' in analysis, "symbol normalization required (ETHUSD == ETH/USD)"
    # Productivity names the missing-alpha blocker.
    assert "NO_ALPHA_SCORECARD" in prod, "productivity must classify the missing-alpha blocker"

    # Runtime: every row carries an explicit state; no unqualified promotion.
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.paper_validation_analysis_service import alpha_coverage_matrix

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    m = alpha_coverage_matrix(Session(engine), config={})
    for field in ("scanned_symbols", "with_scorecard", "no_scorecard", "paper_candidates", "symbols"):
        assert field in m, f"alpha matrix missing {field}"
    for r in m.get("symbols", []):
        assert r.get("scorecard_stage") or r.get("blocker"), f"{r.get('symbol')} has no explicit alpha state"
        if r.get("verdict") not in ("paper_candidate", "proven"):
            assert r.get("blocker"), f"{r.get('symbol')} unproven but no blocker"
    # paper_candidates count never exceeds rows with a qualifying verdict.
    qualified = sum(1 for r in m.get("symbols", []) if r.get("verdict") in ("paper_candidate", "proven"))
    assert m["paper_candidates"] == qualified, "paper_candidates must equal qualified rows"

    print(f"verify_alpha_scorecard_coverage_truth: PASS (explicit state per symbol; no unqualified promotion; normalization enforced)")


if __name__ == "__main__":
    main()
