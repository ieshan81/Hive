"""Header/sidebar must use runtime summary source."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    layout = (ROOT / "src" / "app" / "(dashboard)" / "layout.tsx").read_text(encoding="utf-8")
    runtime = (ROOT / "src" / "lib" / "runtimeTruth.ts").read_text(encoding="utf-8")
    top = (ROOT / "src" / "components" / "layout" / "TopStatusBar.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "src" / "components" / "layout" / "Sidebar.tsx").read_text(encoding="utf-8")
    assert "RuntimeTruthProvider" in layout
    assert "/api/runtime/summary" in runtime
    assert "useRuntimeTruth" in top and "useRuntimeTruth" in sidebar
    assert 'return "Offline"' not in runtime
    assert "configure Alpaca credentials" not in top
    print("verify_ui_runtime_truth_consistency: PASS")


if __name__ == "__main__":
    main()
