"""Capital Allocator API — paper-only budget and exposure control."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/capital-allocator", tags=["capital-allocator"])


@router.get("/status")
def allocator_status(session: Session = Depends(get_session)):
    from app.services.capital_allocator import CapitalAllocatorService

    return CapitalAllocatorService(session).status_summary()


@router.get("/plan")
def allocator_plan(session: Session = Depends(get_session)):
    from app.services.capital_allocator import CapitalAllocatorService

    return CapitalAllocatorService(session).build_plan()


@router.get("/settings")
def allocator_settings(session: Session = Depends(get_session)):
    from app.services.capital_allocator import CapitalAllocatorService

    return CapitalAllocatorService(session).settings()


@router.post("/settings")
def allocator_update_settings(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.capital_allocator import CapitalAllocatorService

    patch = body.get("settings") or body
    out = CapitalAllocatorService(session).update_settings(
        {k: v for k, v in patch.items() if k != "operator"},
        body.get("operator", "operator"),
    )
    session.commit()
    return out
