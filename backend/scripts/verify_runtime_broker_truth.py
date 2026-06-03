"""Runtime summary must not falsely report broker offline when paper is configured."""

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
    from app.services.broker_safety import is_paper_broker_url
    from app.services.config_manager import ConfigManager
    from app.services.runtime_summary_service import build_runtime_summary

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = ConfigManager(session).get_current_readonly()
        summary = build_runtime_summary(session, cfg)
        paper_broker = bool(summary.get("paper_broker") or is_paper_broker_url())
        paper_orders = bool(summary.get("paper_orders_enabled"))
        scheduler_on = bool(summary.get("scheduler_enabled"))

        if paper_broker and paper_orders:
            assert summary.get("broker_connected") is True, summary
        if paper_broker and scheduler_on and summary.get("last_tick_at"):
            assert summary.get("broker_connected") is True, summary

        assert summary.get("broker_mode") in ("paper", "unknown", None) or paper_broker

    print("verify_runtime_broker_truth: PASS")


if __name__ == "__main__":
    main()
