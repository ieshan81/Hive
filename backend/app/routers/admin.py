"""Admin repair endpoints — operator auth required."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.database_bootstrap_service import list_missing_tables, repair_database_bootstrap
from app.services.nuke_reset_service import table_inventory
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/repair-database-bootstrap")
def repair_database_bootstrap_endpoint(
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    return repair_database_bootstrap(session)


@router.get("/table-inventory")
def admin_table_inventory(
    _op: str = Depends(require_operator_token),
):
    return {"status": "ok", **table_inventory(), "missing_tables": list_missing_tables()}
