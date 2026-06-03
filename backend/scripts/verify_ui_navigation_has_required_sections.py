"""Sidebar must expose the 7-page trading-lab IA."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDEBAR = ROOT / "src" / "components" / "layout" / "Sidebar.tsx"

REQUIRED = (
    "/mission-control",
    "/universe",
    "/shadow-league",
    "/paper-candidates",
    "/risk-cage",
    "/evidence-memory",
    "/diagnostics",
)


def main() -> None:
    text = SIDEBAR.read_text(encoding="utf-8")
    missing = [r for r in REQUIRED if r not in text]
    if missing:
        print(f"MISSING nav routes: {missing}")
        sys.exit(1)
    print("verify_ui_navigation_has_required_sections: PASS")


if __name__ == "__main__":
    main()
