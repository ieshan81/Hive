"""UI must not label paper broker as Offline when runtime truth says paper is configured."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    runtime = (ROOT / "src" / "lib" / "runtimeTruth.ts").read_text(encoding="utf-8")
    sidebar = (ROOT / "src" / "components" / "layout" / "Sidebar.tsx").read_text(encoding="utf-8")
    safety = (ROOT / "src" / "components" / "layout" / "SafetyBanner.tsx").read_text(encoding="utf-8")
    provider = (ROOT / "src" / "components" / "layout" / "RuntimeTruthProvider.tsx").read_text(encoding="utf-8")

    assert 'return "Offline"' not in runtime, "brokerLabel must not return Offline for paper runtime"
    assert "live-lock-tripwire" not in safety, "SafetyBanner must not fall back to tripwire"
    assert "Loading…" in sidebar or "Loading" in sidebar
    assert "truthRef" in provider or "truthRef.current" in provider

    print("verify_ui_no_false_broker_offline: PASS")


if __name__ == "__main__":
    main()
