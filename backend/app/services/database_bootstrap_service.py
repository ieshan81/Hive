"""Self-heal missing schema/rows after empty or manual DB recovery."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, select

from app.database import SystemHealth, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.nuke_epoch_service import nuke_status_export


def list_missing_tables() -> list[str]:
    expected = set(SQLModel.metadata.tables.keys())
    bind = engine
    try:
        existing = set(inspect(bind).get_table_names())
    except Exception:
        existing = set()
    return sorted(expected - existing)


def repair_database_bootstrap(session: Session) -> dict[str, Any]:
    missing_before = list_missing_tables()
    init_db()
    missing_after = list_missing_tables()

    config = ConfigManager(session).get_current()
    lock = live_lock_tripwire_status(config)

    from app.services.strategy_engine import StrategyEngine
    from app.services.strategy_promotion_seed import seed_promotion_rules

    StrategyEngine(session, config)
    seed_promotion_rules(session)

    h = session.get(SystemHealth, 1)
    if not h:
        session.add(
            SystemHealth(
                id=1,
                alpaca_connected=False,
                gemini_configured=False,
                details={"bootstrapped": True},
            )
        )
        health_action = "created"
    else:
        health_action = "present"

    session.commit()

    return {
        "status": "ok",
        "missing_tables_before": missing_before,
        "missing_tables_after": missing_after,
        "tables_created": [t for t in missing_before if t not in missing_after],
        "database_bootstrap_status": {
            "schema_ok": len(missing_after) == 0,
            "system_health": health_action,
            "config_current": "present",
        },
        "live_lock": lock,
        "live_trading_enabled": False,
        "learning_scheduler_unchanged": True,
        "nuke_status": nuke_status_export(session),
        "message": "Database bootstrap repair complete. Schema and baseline rows ensured.",
    }
