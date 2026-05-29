"""Verify Mission Control page does not fan out to cockpit/universe reads."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    mission = (ROOT / "src/components/panels/MissionControlPanel.tsx").read_text(encoding="utf-8")
    why = (ROOT / "src/components/panels/WhyNoTradeCard.tsx").read_text(encoding="utf-8")
    assert 'apiGet<MissionControlStatus>("/api/mission-control/status"' in mission
    assert mission.count("apiGet<") == 1
    assert "/api/cockpit" not in mission
    assert "/api/universe/execution-shortlist" not in mission
    assert "apiGet" not in why
    assert "useEffect" not in why
    print("verify_frontend_mission_control_single_get: PASS")


if __name__ == "__main__":
    main()
