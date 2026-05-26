"""Activity logging helper."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.database import ActivityLog


def log_activity(
    session: Session,
    event_type: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
    *,
    commit: bool = True,
) -> ActivityLog:
    row = ActivityLog(event_type=event_type, message=message, details=details)
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    else:
        session.flush()
    return row
