"""Cockpit copy uses clear entries-vs-exits wording, not the conflated 'Bot can trade: NO'.

Static assertion over CockpitDashboard.tsx: the misleading single verdict is gone and the
panel exposes separate 'New entries' / 'Exits allowed' truth plus the entries/exits summary.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TSX = ROOT / "src" / "components" / "cockpit" / "CockpitDashboard.tsx"


def test_cockpit_copy_separates_entries_and_exits() -> None:
    assert TSX.exists(), f"missing {TSX}"
    text = TSX.read_text(encoding="utf-8")
    # The conflated label must be gone.
    assert "Bot can trade" not in text, "stale conflated 'Bot can trade' label still present"
    # Entries are now described as entries, and exits are surfaced separately.
    assert "New paper entries" in text, "missing entries-specific tile"
    assert "New entries allowed" in text, "missing 'New entries allowed' row"
    assert "Exits allowed" in text, "missing 'Exits allowed' row"
    # The component derives + renders an explicit entries/exits summary.
    assert "exitsAllowed" in text, "missing exitsAllowed derivation"
    assert "entriesExitsSummary" in text, "missing entriesExitsSummary derivation"
    assert "exits_allowed" in text, "missing exits_allowed field binding"
    print("cockpit-copy: entries-vs-exits wording present; 'Bot can trade' removed — PASS")


if __name__ == "__main__":
    test_cockpit_copy_separates_entries_and_exits()
    print("ALL PASS: verify_cockpit_trade_permission_copy")
    sys.exit(0)
