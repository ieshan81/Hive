"""Evidence Memory uses new route / graceful empty state."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "src" / "components" / "panels" / "HiveMemoryGraphPanel.tsx"
API = ROOT / "backend" / "app" / "routers" / "api.py"


def main() -> None:
    panel = PANEL.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    assert "/api/evidence-memory/graph" in panel
    assert "/api/evidence-memory/node/" in panel
    assert '"/evidence-memory/graph"' in api or "/evidence-memory/graph" in api
    assert "No evidence memory yet" in panel
    print("verify_ui_evidence_memory_route: PASS")


if __name__ == "__main__":
    main()
