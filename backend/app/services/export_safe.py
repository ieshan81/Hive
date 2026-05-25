"""Safe JSON export helpers — no secrets, no detached ORM instances."""

from __future__ import annotations

import traceback
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

from sqlmodel import SQLModel


def json_safe(value: Any) -> Any:
    """Recursively convert values for JSON / zip export."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat() + ("Z" if isinstance(value, datetime) else "")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, SQLModel):
        return json_safe(value.model_dump(mode="python"))
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="python"))
    return str(value)


def safe_export_section(
    name: str,
    fn: Callable[[], Any],
    errors: list[dict[str, Any]],
) -> Any:
    """Run one diagnostic section; record failure without raising."""
    try:
        return json_safe(fn())
    except Exception as exc:
        errors.append(
            {
                "section": name,
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
                "traceback_summary": traceback.format_exc()[-2000:],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        return {
            "status": "error",
            "section": name,
            "error_type": type(exc).__name__,
            "message": str(exc)[:300],
        }
