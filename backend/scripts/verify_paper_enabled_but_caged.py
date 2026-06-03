"""Verify paper can be enabled while live remains locked and stock lane is readiness-only."""

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
    from app.services.engine_config import cfg_get
    from app.services.paper_validation_productivity_service import build_productivity

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        prod = build_productivity(session, cfg)
        assert prod.get("live_trading_locked") is True
        assert cfg_get(cfg, "execution.live_orders_enabled", True) is False
        assert cfg_get(cfg, "live_trading_enabled", True) is False
        lane = prod.get("stock_lane") or {}
        assert lane.get("stock_entries_allowed") is False
    print("verify_paper_enabled_but_caged: PASS")


if __name__ == "__main__":
    main()
