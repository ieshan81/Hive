"""Live order flags remain disabled — paper canary never enables live."""

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
    from app.services.default_config import DEFAULT_CONFIG
    from app.services.engine_config import cfg_get
    from app.services.paper_canary_gate_service import _canary_cfg

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    for cfg in (DEFAULT_CONFIG, ConfigManager(Session(engine)).get_current()):
        assert cfg_get(cfg, "live_trading_enabled", True) is False
        assert cfg_get(cfg, "execution.live_orders_enabled", True) is False
        assert _canary_cfg(cfg).get("live_forbidden", True) is True
    print("verify_no_live_orders_enabled: PASS")


if __name__ == "__main__":
    main()
