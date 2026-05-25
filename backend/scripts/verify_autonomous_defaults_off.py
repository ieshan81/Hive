"""Autonomous paper learning and scheduler default off in config."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG


def main() -> None:
    apl = DEFAULT_CONFIG.get("autonomous_paper_learning") or {}
    assert apl.get("mode_enabled") is False, "mode_enabled must default false"
    assert apl.get("scheduler_enabled") is False, "scheduler_enabled must default false"
    print("PASS: autonomous defaults off")


if __name__ == "__main__":
    main()
