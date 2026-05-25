"""Application startup helpers."""

from __future__ import annotations

from sqlmodel import Session

from app.database import engine
from app.services.config_manager import ConfigManager
from app.services.strategy_engine import StrategyEngine


def bootstrap_database() -> None:
    """Ensure config and strategy state rows exist before first cycle."""
    with Session(engine) as session:
        ConfigManager(session).get_current()
        StrategyEngine(session, ConfigManager(session).get_current())
        from app.services.memory_reclassify import reclassify_existing_lessons

        n = reclassify_existing_lessons(session)
        from app.services.strategy_promotion_seed import seed_promotion_rules

        seed_promotion_rules(session)
        if n:
            session.commit()
        else:
            session.commit()
