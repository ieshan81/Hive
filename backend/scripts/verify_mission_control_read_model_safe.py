"""Verify Mission Control read model does not call heavy providers/scorers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.mission_control_read_model import build_mission_control_status


def fail(*_args, **_kwargs):
    raise AssertionError("dashboard read model called a heavy provider/scorer")


def main() -> None:
    init_db()
    with Session(engine) as session:
        with patch("app.services.alpaca_adapter.AlpacaAdapter.sync_account_cached", fail), patch(
            "app.services.alpaca_adapter.AlpacaAdapter.sync_positions_cached", fail
        ), patch("app.services.push_pull_scoring_service.score_active_universe", fail), patch(
            "app.services.universe_strategy_discovery_service.build_funnel_breakdown", fail
        ):
            payload = build_mission_control_status(session)
    assert payload["schema_version"] == "mission_control_read_model.v1"
    assert "account" in payload
    assert "universe" in payload
    assert "paper_execution" in payload
    print("verify_mission_control_read_model_safe: PASS")


if __name__ == "__main__":
    main()
