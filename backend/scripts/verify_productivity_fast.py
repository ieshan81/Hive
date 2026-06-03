"""Productivity endpoint must return quickly with why_no_trade."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.config_manager import ConfigManager
    from app.services.paper_validation_productivity_service import build_productivity

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = ConfigManager(session).get_current_readonly()
        t0 = time.time()
        prod = build_productivity(session, cfg, fast_path=True)
        elapsed = time.time() - t0
        assert elapsed < 8.0, f"productivity too slow: {elapsed:.2f}s"
        assert prod.get("fast_path") is True, prod
        assert prod.get("why_no_trade") or prod.get("why_no_paper_trade_plain"), prod
        assert prod.get("status") in ("ok", "degraded"), prod

    print(f"verify_productivity_fast: PASS ({elapsed:.2f}s)")


if __name__ == "__main__":
    main()
