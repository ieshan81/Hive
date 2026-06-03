"""Universe UI must reference summary semantics (no false-zero cards)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "src" / "components" / "panels" / "UniversePanel.tsx"


def main() -> None:
    text = PANEL.read_text(encoding="utf-8")
    for needle in ("/api/universe/summary", "source_counts", "funnel_counts", "display_counts"):
        if needle not in text:
            print(f"MISSING: {needle}")
            sys.exit(1)
    print("verify_ui_no_false_zero_runtime_status: PASS")


if __name__ == "__main__":
    main()
