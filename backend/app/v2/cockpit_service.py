"""AI-first trading cockpit — one live payload, zero snapshot caches."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, ExecutionLog, PositionSnapshot
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.dynamic_weights_service import get_dynamic_weights
from app.services.product_truth_service import product_truth
from app.services.push_pull_scoring_service import score_active_universe
from app.v2.live_pipeline import live_funnel
from app.v2.watchlist import live_full_watchlist


def build_cockpit(session: Session) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    generated = datetime.utcnow().isoformat() + "Z"

    alpaca = AlpacaAdapter(session)
    if alpaca.configured:
        alpaca.sync_account_cached(force=True)
        alpaca.sync_positions_cached(force=True)

    wl = live_full_watchlist(session, force=True)
    funnel = live_funnel(session, cfg)
    truth = product_truth(session, cfg)
    scores = score_active_universe(session, cfg, limit=12)
    weights = get_dynamic_weights(session)

    account = session.exec(
        select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())
    ).first()
    positions = list(session.exec(select(PositionSnapshot)).all())
    logs = list(
        session.exec(select(ExecutionLog).order_by(ExecutionLog.submitted_at.desc()).limit(15)).all()
    )

    score_rows = scores.get("scores") or []
    passed = [s for s in score_rows if s.get("pass") or s.get("entry_allowed")]

    return {
        "status": "ok",
        "generated_at_utc": generated,
        "live_truth": True,
        "cached_snapshot": False,
        "paper_only": True,
        "live_locked": True,
        "account": {
            "connected": alpaca.configured,
            "equity": account.equity if account else None,
            "cash": account.cash if account else None,
            "daily_pl": account.daily_pl if account else None,
        },
        "watchlist": wl,
        "funnel": funnel.get("funnel"),
        "shortlist": funnel.get("shortlist"),
        "why_zero_shortlist": funnel.get("why_zero_shortlist"),
        "block_breakdown": funnel.get("block_breakdown"),
        "scores": score_rows[:12],
        "passed_count": len(passed),
        "weights": weights,
        "control": {
            "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
            "paper_learning_on": bool(truth.get("operator_desired_paper_learning"))
            and truth.get("current_mode") not in ("paper_learning_off", "off", "env_paused"),
            "bot_can_place": truth.get("effective_can_place_paper_orders"),
            "blockers": truth.get("blockers") or truth.get("blocker_codes") or [],
            "mode": truth.get("current_mode"),
        },
        "positions": [
            {
                "symbol": p.symbol,
                "qty": p.quantity,
                "side": p.side,
                "market_value": p.market_value,
                "unrealized_pl": p.unrealized_pl,
            }
            for p in positions
        ],
        "recent_trades": [
            {
                "symbol": r.symbol,
                "side": r.side,
                "status": r.status,
                "quantity": r.requested_qty,
                "submitted_at": r.submitted_at.isoformat() + "Z" if r.submitted_at else None,
            }
            for r in logs
        ],
        "ai_cockpit_message": _cockpit_narrative(funnel, truth, passed, weights),
    }


def _cockpit_narrative(funnel: dict, truth: dict, passed: list, weights: dict) -> str:
    f = funnel.get("funnel") or {}
    parts = [
        f"Watchlist funnel: {f.get('available', 0)} available → {f.get('shortlist', 0)} shortlist.",
        f"Paper learning {'ON' if truth.get('operator_desired_paper_learning') else 'OFF'}.",
        f"Bot may trade: {'YES' if truth.get('effective_can_place_paper_orders') else 'NO'}.",
    ]
    if passed:
        parts.append(f"Top setup: {passed[0].get('symbol')} quality {passed[0].get('quality_score', 0):.0f}.")
    if funnel.get("why_zero_shortlist"):
        parts.append(f"Blockers: {funnel['why_zero_shortlist']}")
    uw = weights.get("universe_ranking") or {}
    if uw:
        top_w = max(uw.items(), key=lambda x: float(x[1]))
        parts.append(f"Strongest rank weight: {top_w[0]} ({float(top_w[1])*100:.0f}%).")
    return " ".join(parts)
