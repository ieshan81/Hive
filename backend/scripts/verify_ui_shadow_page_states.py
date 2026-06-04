"""Shadow page enabled+zero must show waiting, not disabled."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "src" / "components" / "panels" / "ShadowLeaguePanel.tsx"


def main() -> None:
    text = PANEL.read_text(encoding="utf-8")
    assert "Shadow learning active — waiting for setups" in text
    assert "reason_shadow_count_zero" in text
    assert "Why zero:" in text
    assert 'effective?.enabled === false && effective?.ui_state === "disabled_by_config"' in text
    assert "WAITING_STATES" in text
    assert "ui_state" in text
    print("verify_ui_shadow_page_states: PASS")


if __name__ == "__main__":
    main()
