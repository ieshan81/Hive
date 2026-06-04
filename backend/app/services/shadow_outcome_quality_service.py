"""Aggregate shadow outcome quality metrics for bundle and status."""

from __future__ import annotations

from statistics import median
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ShadowTrade
from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_CLOSED, STATUS_OPEN


def build_shadow_outcome_quality(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    run_id = (get_latest_reset_epoch(session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID
    rows = list(
        session.exec(select(ShadowTrade).where(ShadowTrade.validation_run_id == run_id)).all()
    )
    l1 = [r for r in rows if r.promotion_level >= LEVEL_SHADOW_TRADE]
    closed = [r for r in l1 if r.status == STATUS_CLOSED]
    open_n = [r for r in l1 if r.status == STATUS_OPEN]
    pnls = [float(r.simulated_pnl_bps) for r in closed if r.simulated_pnl_bps is not None]
    wins = sum(1 for r in closed if r.outcome_verdict == "win")
    losses = sum(1 for r in closed if r.outcome_verdict == "loss")
    flats = sum(1 for r in closed if r.outcome_verdict in ("flat", "unknown"))
    zero_pnl = sum(1 for r in closed if r.simulated_pnl_bps is not None and abs(r.simulated_pnl_bps) < 0.5)
    instant = 0
    reason_counts: dict[str, int] = {}
    min_hold = float((config or {}).get("shadow_league", {}).get("min_hold_seconds", 90))

    for r in closed:
        oj = r.outcome_json or {}
        reason = str(oj.get("exit_reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        hold = float(oj.get("hold_seconds") or 0)
        if hold < min_hold and reason not in ("missing_price_data", "missing_entry_price", "max_open_cap_release"):
            instant += 1

    avg_pnl = round(sum(pnls) / len(pnls), 2) if pnls else None
    med_pnl = round(median(pnls), 2) if pnls else None

    return {
        "validation_run_id": run_id,
        "open_count": len(open_n),
        "closed_count": len(closed),
        "wins": wins,
        "losses": losses,
        "flat_or_unknown": flats,
        "avg_pnl_bps": avg_pnl,
        "median_pnl_bps": med_pnl,
        "zero_pnl_closed_count": zero_pnl,
        "instant_close_count": instant,
        "close_reason_counts": reason_counts,
        "counts_as_broker_evidence": False,
        "broker_orders_from_shadow": 0,
    }
