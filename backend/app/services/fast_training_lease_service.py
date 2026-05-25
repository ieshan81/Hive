"""DB lease for fast-training run-once — no overlapping runs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session

from app.database import FastTrainingLease

LEASE_KEY = "fast_training_run"
DEFAULT_TTL_SECONDS = 120


class FastTrainingLeaseService:
    def __init__(self, session: Session, *, use_db_lease: bool = True, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.session = session
        self.use_db_lease = use_db_lease
        self.ttl_seconds = ttl_seconds

    def _row(self) -> FastTrainingLease:
        row = self.session.get(FastTrainingLease, LEASE_KEY)
        if not row:
            row = FastTrainingLease(lease_key=LEASE_KEY)
            self.session.add(row)
            self.session.flush()
        return row

    def status(self) -> dict[str, Any]:
        row = self._row()
        now = datetime.utcnow()
        held = bool(row.holder_id and row.expires_at and row.expires_at > now)
        return {
            "use_db_lease": self.use_db_lease,
            "lease_held": held,
            "holder_id": row.holder_id,
            "acquired_at": row.acquired_at.isoformat() + "Z" if row.acquired_at else None,
            "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
            "last_completed_at": row.last_completed_at.isoformat() + "Z" if row.last_completed_at else None,
            "last_result": row.last_result_json,
        }

    def acquire(self, holder_id: Optional[str] = None) -> tuple[bool, str]:
        if not self.use_db_lease:
            return True, holder_id or f"no-lease-{uuid.uuid4().hex[:8]}"
        hid = holder_id or f"run-{uuid.uuid4().hex[:12]}"
        row = self._row()
        now = datetime.utcnow()
        if row.holder_id and row.expires_at and row.expires_at > now and row.holder_id != hid:
            return False, row.holder_id
        row.holder_id = hid
        row.acquired_at = now
        row.expires_at = now + timedelta(seconds=self.ttl_seconds)
        self.session.add(row)
        self.session.flush()
        return True, hid

    def release(self, holder_id: str, result: Optional[dict] = None) -> None:
        if not self.use_db_lease:
            return
        row = self._row()
        if row.holder_id != holder_id:
            return
        row.holder_id = None
        row.acquired_at = None
        row.expires_at = None
        row.last_completed_at = datetime.utcnow()
        if result is not None:
            row.last_result_json = result
        self.session.add(row)
        self.session.flush()
