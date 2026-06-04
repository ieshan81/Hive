"""Bundle/API export for last-tick shadow diagnostics."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import ShadowTrade
from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch
from app.services.shadow_league_constants import LEVEL_OBSERVED


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def build_shadow_tick_diagnostics_export(
    session: Session,
    config: dict,
    *,
    scheduler: Optional[dict] = None,
) -> dict[str, Any]:
    if scheduler is None:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        scheduler = AutonomousPaperScheduler(session, config).status()
    diag = dict(scheduler.get("last_shadow_diagnostics") or {})
    if not diag.get("observation_floor"):
        from app.services.shadow_tick_diagnostics import build_shadow_tick_diagnostics

        diag = build_shadow_tick_diagnostics(
            config,
            rows_scored=0,
            rows_above_observation_floor=0,
            rows_above_shadow_floor=0,
            max_setup_quality=0.0,
            quality_scale="0_100",
            shadow_attempts=0,
            shadow_observations_created=0,
            shadow_trades_created=0,
            shadow_errors=0,
            near_misses=[],
            skip_reason_counts={},
        )
    run_id = (get_latest_reset_epoch(session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID
    obs_n = int(
        session.exec(
            select(func.count())
            .select_from(ShadowTrade)
            .where(
                ShadowTrade.validation_run_id == run_id,
                ShadowTrade.promotion_level == LEVEL_OBSERVED,
            )
        ).one()
        or 0
    )
    total_n = int(
        session.exec(
            select(func.count()).select_from(ShadowTrade).where(ShadowTrade.validation_run_id == run_id)
        ).one()
        or 0
    )
    return {
        "generated_at": _now(),
        "validation_run_id": run_id,
        "total_shadow_records": total_n,
        "total_shadow_observations_l0": obs_n,
        "reason_shadow_count_zero": scheduler.get("reason_shadow_count_zero")
        or diag.get("last_tick_zero_shadow_reason"),
        **diag,
        "scheduler_last_tick_at": scheduler.get("last_tick_at"),
        "last_tick_shadow_observations": scheduler.get("last_shadow_setups_observed"),
        "note": "Diagnostics from last scheduler tick shadow pass over all ranked push-pull scores.",
    }
