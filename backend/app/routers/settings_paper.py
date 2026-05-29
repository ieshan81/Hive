"""
Paper-trading Settings API.

  GET  /api/settings/status                 — read-only system mode + paper subset
  GET  /api/settings/paper-trading          — read-only paper config subset
  GET  /api/settings/paper-trading/readiness — cockpit-truth readiness (no order submit)
  POST /api/settings/paper-trading/dry-run   — preview a change set or preset
  POST /api/settings/paper-trading/apply     — operator-protected mutation through ConfigManager
  POST /api/settings/paper-trading/pause     — disable paper learning + scheduler
  POST /api/settings/paper-trading/resume    — enable paper learning + scheduler
  POST /api/settings/paper-trading/enable-orders   — set execution.paper_orders_enabled True
  POST /api/settings/paper-trading/disable-orders  — set execution.paper_orders_enabled False
  POST /api/execution/paper/readiness-check  — alias for readiness (spec-compatible path)

Live trading is never touched here. Mutating routes:
  - require the operator token
  - reject actor_type == "ai"
  - write through ConfigManager._activate (audit log)
  - never submit orders or run cycles
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token
from app.services import paper_settings_service as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])

# The /api/execution/paper/{status,readiness-check} endpoints already exist in
# routers/api.py. This module intentionally does NOT redefine them to avoid
# duplicate route registrations; it only adds /api/settings/* and reuses the
# existing paper readiness check.


def _actor_from_body(body: dict | None) -> tuple[str, str]:
    body = body or {}
    actor = str(body.get("actor") or body.get("operator") or "operator")
    actor_type = str(body.get("actor_type") or "operator")
    return actor, actor_type


@router.get("/status")
def status_endpoint(session: Session = Depends(get_session)):
    return svc.settings_status(session)


@router.get("/paper-trading")
def paper_trading_get(session: Session = Depends(get_session)):
    return svc.paper_settings(session)


@router.get("/paper-trading/readiness")
def paper_trading_readiness(session: Session = Depends(get_session)):
    return svc.paper_readiness(session)


@router.post("/paper-trading/dry-run")
def paper_trading_dry_run(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor, actor_type = _actor_from_body(body)
    if actor_type.lower() == "ai":
        raise HTTPException(403, "AI cannot dry-run paper settings")
    return svc.dry_run(session, body, actor=actor)


@router.post("/paper-trading/apply")
def paper_trading_apply(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor, actor_type = _actor_from_body(body)
    if actor_type.lower() == "ai":
        raise HTTPException(403, "AI cannot apply paper settings")
    out = svc.apply(session, body, actor=actor, actor_type=actor_type)
    session.commit()
    return out


@router.post("/paper-trading/pause")
def paper_trading_pause(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor, actor_type = _actor_from_body(body)
    if actor_type.lower() == "ai":
        raise HTTPException(403, "AI cannot pause paper learning")
    out = svc.set_paper_learning(session, enabled=False, actor=actor, actor_type=actor_type)
    session.commit()
    return out


@router.post("/paper-trading/resume")
def paper_trading_resume(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor, actor_type = _actor_from_body(body)
    if actor_type.lower() == "ai":
        raise HTTPException(403, "AI cannot resume paper learning")
    out = svc.set_paper_learning(session, enabled=True, actor=actor, actor_type=actor_type)
    session.commit()
    return out


@router.post("/paper-trading/enable-orders")
def paper_trading_enable_orders(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor, actor_type = _actor_from_body(body)
    if actor_type.lower() == "ai":
        raise HTTPException(403, "AI cannot enable paper orders")
    out = svc.set_paper_orders(session, enabled=True, actor=actor, actor_type=actor_type)
    session.commit()
    return out


@router.post("/paper-trading/disable-orders")
def paper_trading_disable_orders(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    actor, actor_type = _actor_from_body(body)
    if actor_type.lower() == "ai":
        raise HTTPException(403, "AI cannot disable paper orders")
    out = svc.set_paper_orders(session, enabled=False, actor=actor, actor_type=actor_type)
    session.commit()
    return out


# NOTE: /api/execution/paper/{status,readiness-check} are intentionally NOT
# defined here — they live in routers/api.py.
