"""Latest diagnostic bundle must export shadow league JSON sections."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REQUIRED = (
    "shadow_trades_summary.json",
    "shadow_outcomes.json",
    "strategy_promotion_ladder.json",
    "why_no_trade.json",
)


def main() -> None:
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "diagnostic_bundle_latest.py"
    text = src.read_text(encoding="utf-8")
    missing = [k for k in REQUIRED if k not in text]
    if missing:
        print(f"MISSING: {missing}")
        sys.exit(1)
    print("verify_shadow_league_bundle_sections: PASS")


if __name__ == "__main__":
    main()
