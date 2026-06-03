"""Assert fast runtime endpoints agree on core truth fields."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.config_manager import ConfigManager
    from app.services.mission_control_read_model import build_mission_control_tiles
    from app.services.paper_execution_service import PaperExecutionService
    from app.services.paper_validation_productivity_service import build_productivity
    from app.services.runtime_summary_service import build_runtime_summary
    from app.services.shadow_league_status_service import build_shadow_league_status

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = ConfigManager(session).get_current_readonly()
        summary = build_runtime_summary(session, cfg)
        tiles = build_mission_control_tiles(session)
        prod = build_productivity(session, cfg)
        shadow = build_shadow_league_status(session, cfg)
        paper = PaperExecutionService(session, cfg).status()
        pe = tiles.get("paper_execution") or {}

        checks = [
            ("scheduler_enabled", summary.get("scheduler_enabled"), pe.get("scheduler_enabled")),
            ("live_locked", summary.get("live_locked"), pe.get("live_trading_locked")),
            ("broker_mode", summary.get("broker_mode"), tiles.get("broker_mode")),
            ("paper_orders_enabled", summary.get("paper_orders_enabled"), prod.get("paper_trading_enabled")),
            ("paper_entry_ready", summary.get("paper_entry_ready"), paper.get("paper_entry_ready")),
            ("shadow_league_enabled", summary.get("shadow_league_enabled"), shadow.get("enabled")),
            ("validation_run_id", summary.get("validation_run_id"), prod.get("validation_run_id")),
        ]
        for name, a, b in checks:
            assert a == b, f"{name}: runtime={a!r} other={b!r}"

        assert prod.get("paper_entry_ready") == paper.get("paper_entry_ready"), (
            prod.get("paper_entry_ready"),
            paper.get("paper_entry_ready"),
        )
    print("verify_runtime_truth_consistency: PASS")


if __name__ == "__main__":
    main()
