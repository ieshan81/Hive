"""Operator universe — merged scan sources (never empty when radar has symbols)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PaperExperimentDecision
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import get_latest_reset_epoch, record_created_after
from app.services.universe_builder import build_merged_universe


def universe_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    epoch = get_latest_reset_epoch(session)
    rows = build_merged_universe(session, config, limit=80)

    stock = [r for r in rows if r.get("asset_type") == "Stock"]
    crypto = [r for r in rows if r.get("asset_type") == "Crypto"]
    active = [r for r in rows if r.get("status") == "Active"]
    blocked = [r for r in rows if r.get("status") == "Blocked"]
    watch = [r for r in rows if r.get("status") == "Watch-only"]

    decisions = list(
        session.exec(
            select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(100)
        ).all()
    )
    if epoch:
        cutoff = epoch.get("nuke_completed_at")
        decisions = [d for d in decisions if record_created_after(d, cutoff)]

    return {
        "status": "ok",
        "reset_epoch": epoch,
        "total_symbols": len(rows),
        "counts": {
            "total": len(rows),
            "stock": len(stock),
            "crypto": len(crypto),
            "active": len(active),
            "blocked": len(blocked),
            "watch_only": len(watch),
        },
        "groups": {
            "stock_universe": stock,
            "crypto_universe": crypto,
            "active_push_pull_candidates": active,
            "blocked_unsupported": blocked,
            "watch_only": watch,
            "recently_rejected": _recent_rejected(decisions)[:30],
        },
        "symbols": rows,
    }


def universe_scan_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    st = universe_status(session, config)
    return {
        "status": "ok",
        "total_symbols": st.get("total_symbols"),
        "counts": st.get("counts"),
        "reset_epoch": st.get("reset_epoch"),
    }


def _recent_rejected(decisions: list) -> list[dict]:
    out = []
    for d in decisions:
        if d.decision != "approved":
            out.append(
                {
                    "symbol": d.symbol,
                    "reason_code": d.reason_code,
                    "reason_text": d.reason_text,
                    "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
                }
            )
    return out
