"""Cockpit shows the honest four-lane truth: Real Money LOCKED, Standard Paper Entries
BLOCKED/ALLOWED, Paper Exploration ALLOWED/BLOCKED, Exit Management ACTIVE, plus the current
exploration candidate. Static assertion over CockpitDashboard.tsx."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TSX = ROOT / "src" / "components" / "cockpit" / "CockpitDashboard.tsx"


def main() -> None:
    assert TSX.exists(), f"missing {TSX}"
    text = TSX.read_text(encoding="utf-8")
    for needle in (
        "Real Money",
        "LOCKED",
        "Standard Paper Entries",
        "Paper Exploration",
        "Exit Management",
        "current_exploration_candidate",
        "paper_exploration_allowed",
    ):
        assert needle in text, f"cockpit missing '{needle}'"
    # Real money must be hard-locked text, not a boolean toggle that could read ALLOWED.
    assert '["Real Money", "LOCKED"' in text, "Real Money must render LOCKED"
    # Exploration shows ALLOWED/BLOCKED state.
    assert "ALLOWED" in text and "BLOCKED" in text, "exploration state labels missing"
    print("verify_cockpit_shows_real_money_locked_but_paper_exploration_state: PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
