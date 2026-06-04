"""Diagnostic bundle sections for Shadow Trading League."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ShadowTrade
from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch
from app.services.shadow_league_constants import LEVEL_LABELS, STATUS_CLOSED, STATUS_OPEN
from app.services.shadow_promotion_ladder_service import ShadowPromotionLadderService


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _ser(row: ShadowTrade) -> dict[str, Any]:
    return {
        "shadow_trade_id": row.shadow_trade_id,
        "symbol": row.symbol,
        "asset_class": row.asset_class,
        "strategy_id": row.strategy_id,
        "promotion_level": row.promotion_level,
        "level_name": LEVEL_LABELS.get(row.promotion_level),
        "status": row.status,
        "data_quality": row.data_quality,
        "data_quality_note": row.data_quality_note,
        "outcome_verdict": row.outcome_verdict,
        "simulated_pnl_bps": row.simulated_pnl_bps,
        "entry_reference_price": row.entry_reference_price,
        "exit_reference_price": row.exit_reference_price,
        "exit_reason": (row.outcome_json or {}).get("exit_reason"),
        "paper_blocked_reason": row.paper_blocked_reason,
        "counts_as_broker_evidence": bool(row.counts_as_broker_evidence),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "closed_at": row.closed_at.isoformat() + "Z" if row.closed_at else None,
    }


def shadow_outcome_quality(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.shadow_outcome_quality_service import build_shadow_outcome_quality

    out = build_shadow_outcome_quality(session, config)
    out["generated_at"] = _now()
    return out


def shadow_trades_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    run_id = (get_latest_reset_epoch(session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID
    rows = list(
        session.exec(select(ShadowTrade).where(ShadowTrade.validation_run_id == run_id)).all()
    )
    open_n = sum(1 for r in rows if r.status == STATUS_OPEN)
    closed_n = sum(1 for r in rows if r.status == STATUS_CLOSED)
    return {
        "generated_at": _now(),
        "validation_run_id": run_id,
        "shadow_league_count": len(rows),
        "open_shadow_trades": open_n,
        "closed_shadow_trades": closed_n,
        "counts_as_broker_evidence": False,
        "broker_orders_from_shadow": 0,
        "note": "Shadow trades never call Alpaca or PaperExecutionService.",
    }


def shadow_outcomes(session: Session, config: Optional[dict] = None, *, cap: int = 100) -> dict[str, Any]:
    run_id = (get_latest_reset_epoch(session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID
    rows = list(
        session.exec(
            select(ShadowTrade).where(
                ShadowTrade.validation_run_id == run_id,
                ShadowTrade.status == STATUS_CLOSED,
            )
        ).all()
    )
    rows.sort(key=lambda r: r.closed_at or r.created_at, reverse=True)
    rows = rows[:cap]
    return {
        "generated_at": _now(),
        "validation_run_id": run_id,
        "row_count": len(rows),
        "counts_as_broker_evidence": False,
        "outcomes": [_ser(r) for r in rows],
    }


def strategy_promotion_ladder(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    ladder = ShadowPromotionLadderService(session, config).ladder_summary()
    ladder["generated_at"] = _now()
    return ladder


def why_no_trade(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.mission_control_read_model import build_mission_control_status

    mc = build_mission_control_status(session)
    wnt = mc.get("why_no_trade_summary") or {}
    ladder = ShadowPromotionLadderService(session, config).ladder_summary()
    closest = ladder.get("closest_to_paper_promotion") or {}
    return {
        "generated_at": _now(),
        "plain": wnt.get("plain"),
        "top_blockers": wnt.get("top_blockers") or [],
        "shadow_league": {
            "count": ladder.get("total_records"),
            "closest_setup": closest,
            "missing_evidence": closest.get("missing_evidence") or [],
        },
        "paper_path_note": "Broker paper requires cage/alpha gates — shadow L3 is not a broker bypass.",
        "shadow_not_broker_evidence": True,
    }
