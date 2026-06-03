"""Misleading trade labels removed from UI."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    universe = (ROOT / "src" / "components" / "panels" / "UniversePanel.tsx").read_text(encoding="utf-8")
    funnel = (ROOT / "src" / "components" / "cockpit" / "CockpitFunnelBrain.tsx").read_text(encoding="utf-8")
    paper = (ROOT / "src" / "components" / "panels" / "PaperCandidatesPanel.tsx").read_text(encoding="utf-8")
    assert "Shortlist" in universe and "Shortlist" in funnel
    assert "To trade" not in funnel
    assert "Eligible trades" not in universe
    assert "Paper candidates" in universe
    assert "Live locked — expected" in paper
    print("verify_ui_no_misleading_trade_labels: PASS")


if __name__ == "__main__":
    main()
