"""Autonomous Paper Learning API — operator-gated, paper only."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/autonomous-paper-learning", tags=["autonomous-paper-learning"])


def _block_ai(body: dict) -> None:
    """Defense-in-depth: AI/advisory actors may never trigger trading activity.

    Operator-token auth already gates these routes; this rejects an AI caller
    even if it somehow holds the token (see app.services.ai_boundaries)."""
    from app.services.ai_boundaries import is_ai_actor

    if is_ai_actor((body or {}).get("actor", "")):
        raise HTTPException(403, "AI/advisory actors may not trigger autonomous paper trading; operator required.")


@router.get("/status")
def apl_status(session: Session = Depends(get_session)):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    return AutonomousPaperLearningService(session).status()


@router.post("/enable")
def apl_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).enable(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/pause")
def apl_pause(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).pause(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/disable-all-paper-trading")
def apl_disable_all(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    out = AutonomousPaperLearningService(session).disable_all_paper_trading(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/run-one-cycle")
def apl_run_one(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    _block_ai(body)
    out = AutonomousPaperLearningService(session).run_one_cycle(operator=body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/run-backtest-lab-now")
def apl_backtest_lab(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

    _block_ai(body)
    out = AutonomousPaperLearningService(session).run_backtest_lab_now(
        operator=body.get("operator", "operator"),
        limit=int(body.get("limit", 3)),
    )
    session.commit()
    return out


@router.get("/scheduler/status")
def scheduler_status(session: Session = Depends(get_session)):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    return AutonomousPaperScheduler(session).status()


@router.post("/scheduler/enable")
def scheduler_enable(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    _block_ai(body)
    out = AutonomousPaperScheduler(session).enable(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/scheduler/pause")
def scheduler_pause(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    out = AutonomousPaperScheduler(session).pause(body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/start-fresh")
def start_fresh(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    _block_ai(body)
    from app.services.paper_learning_start_service import start_fresh_paper_learning

    out = start_fresh_paper_learning(session, operator=body.get("operator", "operator"))
    session.commit()
    return out


@router.post("/tick")
def scheduler_tick(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    _block_ai(body)
    out = AutonomousPaperScheduler(session).tick(operator=body.get("operator", "cron"))
    session.commit()
    return out


@router.post("/supervised-burst")
def supervised_burst(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Run up to N (default 3) operator-supervised ticks, stopping early on any
    material event (order placed/rejected, kill switch, cap hit, duplicate-buy or
    missing-exit-plan block, reconciliation drift, or scheduler pause)."""
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    _block_ai(body)
    out = AutonomousPaperScheduler(session).supervised_burst(
        max_ticks=int(body.get("max_ticks", 3) or 3),
        operator=body.get("operator", "operator"),
    )
    session.commit()
    return out


@router.post("/stop-after-tick")
def stop_after_tick(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Pause the always-on scheduler after the current tick (config untouched; Enable resumes)."""
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    out = AutonomousPaperScheduler(session).stop_after_tick(body.get("operator", "operator"))
    session.commit()
    return out


# ─────────────────────────────────────────────────────────────────────────
# Paper-autopilot journal / diagnostics / export bundle (read-only telemetry)
# ─────────────────────────────────────────────────────────────────────────

@router.get("/journal")
def apl_journal(limit: int = 200, day: str | None = None, session: Session = Depends(get_session)):
    """Recent per-tick paper run journal (newest first). Read-only telemetry."""
    from app.services.paper_autopilot_journal import recent_journal

    entries = recent_journal(session, limit=max(1, min(int(limit or 200), 1000)), day=day)
    return {"status": "ok", "count": len(entries), "entries": entries}


@router.get("/diagnostics")
def apl_diagnostics(days: int = 14, session: Session = Depends(get_session)):
    """Per-day aggregated paper-autopilot diagnostics. Read-only telemetry."""
    from app.services.paper_autopilot_journal import daily_diagnostics

    return {"status": "ok", **daily_diagnostics(session, days=max(1, min(int(days or 14), 60)))}


@router.get("/export-bundle")
def apl_export_bundle(session: Session = Depends(get_session)):
    """One-click Paper Autopilot bundle as JSON (paper telemetry; no secrets)."""
    from app.services.paper_autopilot_journal import paper_autopilot_bundle

    return {"status": "ok", "bundle": paper_autopilot_bundle(session)}


@router.get("/export-bundle/download")
def apl_export_bundle_download(session: Session = Depends(get_session)):
    """Download the Paper Autopilot bundle as a ZIP file."""
    from app.services.paper_autopilot_journal import (
        paper_autopilot_bundle_filename,
        paper_autopilot_bundle_zip,
    )

    data = paper_autopilot_bundle_zip(session)
    filename = paper_autopilot_bundle_filename()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/rotate-daily-bundle")
def apl_rotate_daily_bundle(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """Operator/cron: persist today's compact diagnostics snapshot, retaining newest N days."""
    _block_ai(body)
    from app.services.paper_autopilot_journal import rotate_daily_bundle

    out = rotate_daily_bundle(session, keep=int(body.get("keep", 14) or 14))
    session.commit()
    return {"status": "ok", "snapshot": out}
