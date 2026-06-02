"""Phase 10 verifier: paper_quarantined influence is negative-only (never boosts ranking).

Asserts the alpha rank score SUBTRACTS a penalty for a paper_quarantined/rejected verdict (never
adds), so an identical scorecard ranks strictly LOWER when quarantined, and quarantined verdicts
are excluded from paper candidates.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


class _SC:
    """Duck-typed AlphaScorecard for the pure _rank_score staticmethod."""
    def __init__(self, verdict):
        self.expectancy = 0.5
        self.profit_factor = 1.2
        self.sample_size = 30
        self.edge_after_cost_bps = 20.0
        self.verdict = verdict


def main() -> None:
    af = (BACKEND / "app/services/autonomous_alpha_factory_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    # Penalty is SUBTRACTED (negative-only) and applies to quarantined/rejected.
    assert "- penalty" in af, "rank score must subtract the quarantine/rejected penalty"
    assert 'penalty = 1.0 if sc.verdict in ("rejected", "paper_quarantined") else 0.0' in af, "quarantine penalty missing"
    # Quarantined verdict excluded from paper candidates.
    assert af.count('"paper_quarantined"') >= 2, "paper_quarantined must be handled as non-candidate in promotion paths"

    from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService as F

    clean = F._rank_score(_SC(None))
    quarantined = F._rank_score(_SC("paper_quarantined"))
    rejected = F._rank_score(_SC("rejected"))
    assert quarantined < clean, f"quarantined ({quarantined}) must rank LOWER than clean ({clean})"
    assert rejected < clean, "rejected must rank lower than clean"
    assert abs(quarantined - (clean - 1.0)) < 1e-6, "quarantine effect must be a pure -1.0 penalty (never a boost)"
    # Never a positive influence: quarantined can only equal-or-lower, never exceed clean.
    assert quarantined <= clean and rejected <= clean

    print("verify_paper_quarantined_memory_negative_only: PASS (quarantine subtracts penalty; ranks strictly lower; never boosts)")


if __name__ == "__main__":
    main()
