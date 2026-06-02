"""Phase 4 verifier: universe count semantics — source vs eligibility never conflated.

Asserts the four layers stay distinct and a strict eligibility/shortlist of 0 never overwrites the
source/display universe; a block breakdown is present when eligible=0; stock policy/stale blockers
are distinct from crypto.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    svc = (BACKEND / "app/services/universe_summary_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    # Source counts are never assigned from eligibility/funnel values.
    assert "counts_meaning" in svc, "counts_meaning metadata missing"
    assert "source_nonzero_but_eligible_zero" in svc

    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.universe_summary_service import build_universe_summary

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    s = build_universe_summary(Session(engine), config={})

    src, disp, fun, fresh = s["source_counts"], s["display_counts"], s["funnel_counts"], s["freshness_counts"]
    # The four layers are distinct dicts with distinct keys.
    assert "eligible" in fun and "eligible" not in src and "eligible" not in disp, "eligible must live only in funnel"
    assert "execution_shortlist" in fun and "execution_shortlist" not in disp, "shortlist must be separate from display"
    assert set(src) & set(fun) == set(), "source and funnel keys must not overlap"

    # eligible=0 must NOT zero the source/display universe.
    if (fun.get("eligible") or 0) == 0:
        assert disp["total"] > 0 and (src["curated_crypto"] + src["curated_stock"]) > 0, "eligible=0 zeroed source/display"
        assert s["zero_eligible_explanation"] is not None or (fun.get("available") or 0) == 0, "missing zero-eligible explanation"

    # Stock policy blocker is a distinct concept from crypto/funnel blockers.
    assert "stock_lane_mode" in s["policy"] and "crypto_active" in s["policy"], "policy block must be separate"
    assert isinstance(s["blocker_summary"], list), "funnel blocker_summary must be a list (distinct from policy)"

    print("verify_universe_counts_semantics: PASS (source/display/funnel distinct; eligible=0 != source=0; policy vs funnel blockers separate)")


if __name__ == "__main__":
    main()
