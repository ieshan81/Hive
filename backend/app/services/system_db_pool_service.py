"""Database pool health — detect QueuePool exhaustion."""

from __future__ import annotations

from typing import Any

from app.database import engine


def db_pool_status() -> dict[str, Any]:
    pool = getattr(engine, "pool", None)
    if pool is None:
        return {"status": "ok", "degraded": False, "message": "No connection pool (SQLite default)"}

    status = "ok"
    degraded = False
    checked_out = overflow = pool_size = None
    try:
        pool_size = pool.size()
        checked_out = pool.checkedout()
        overflow = pool.overflow()
        if checked_out is not None and pool_size is not None:
            cap = pool_size + (getattr(pool, "_max_overflow", 0) or 0)
            if cap and checked_out >= cap - 1:
                degraded = True
                status = "degraded"
    except Exception as exc:
        return {"status": "unknown", "degraded": False, "message": str(exc)[:120]}

    return {
        "status": status,
        "degraded": degraded,
        "pool_size": pool_size,
        "checked_out": checked_out,
        "overflow": overflow,
        "pool_pre_ping": True,
        "message": (
            "Connection pool near capacity — avoid heavy exports and burst API traffic."
            if degraded
            else "Pool healthy"
        ),
    }
