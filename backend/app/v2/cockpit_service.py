"""AI-first trading cockpit — one live payload, zero snapshot caches."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, ExecutionLog, LessonNode, PositionSnapshot
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.dynamic_weights_service import get_dynamic_weights
from app.services.product_truth_service import product_truth
from app.services.push_pull_scoring_service import score_active_universe
from app.v2.live_pipeline import live_funnel
from app.v2.watchlist import live_crypto_watchlist, live_full_watchlist, live_stock_watchlist


def _control_from_truth(truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
        "paper_learning_on": bool(truth.get("operator_desired_paper_learning")),
        "bot_can_place": truth.get("effective_can_place_paper_orders"),
        "blockers": truth.get("blockers") or truth.get("blocker_codes") or [],
        "mode": truth.get("current_mode"),
        "mode_label": truth.get("current_mode_label"),
    }


def build_cockpit_summary(session: Session) -> dict[str, Any]:
    """Fast cockpit (<5s) — single source of truth for UI cards + banner."""
    cfg = ConfigManager(session).get_current()
    generated = datetime.utcnow().isoformat() + "Z"
    truth = product_truth(session, cfg)
    alpaca = AlpacaAdapter(session)

    if alpaca.configured:
        try:
            alpaca.sync_account_cached(force=False)
        except Exception:
            pass

    account = session.exec(
        select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())
    ).first()
    crypto = live_crypto_watchlist(force=False)
    stocks = live_stock_watchlist(session)

    from app.services.trader_console_service import trader_console_status

    tc = trader_console_status(session)
    shortlist = tc.get("eligible_trades") or tc.get("shortlist") or []
    breakdown = tc.get("no_trade_reason_breakdown") or {}

    positions = list(session.exec(select(PositionSnapshot)).all())
    lesson_rows = list(
        session.exec(
            select(LessonNode)
            .where(LessonNode.status == "active")
            .order_by(LessonNode.updated_at.desc())
            .limit(5)
        ).all()
    )
    lesson_total = len(
        list(session.exec(select(LessonNode).where(LessonNode.status == "active")).all())
    )
    logs = list(
        session.exec(select(ExecutionLog).order_by(ExecutionLog.submitted_at.desc()).limit(8)).all()
    )

    avail = int(crypto.get("usd_pairs") or len(crypto.get("symbols") or []))
    eligible_n = len(shortlist)
    fresh_n = int(tc.get("fresh_count") or 0)
    stale_n = int(breakdown.get("stale_bar") or breakdown.get("data_stale") or 0)
    if fresh_n <= 0 and avail > 0 and stale_n < avail:
        fresh_n = max(0, avail - stale_n)

    zero_reason = None
    if not shortlist:
        top = sorted(breakdown.items(), key=lambda x: -x[1])[:3]
        if top:
            zero_reason = "; ".join(f"{k}: {v}" for k, v in top)
        elif tc.get("message"):
            zero_reason = str(tc.get("message"))

    funnel = {
        "available": avail,
        "cached": avail,
        "fresh": fresh_n if fresh_n > 0 else max(0, avail - stale_n),
        "eligible": int(tc.get("eligible_count") or eligible_n),
        "ranked": int(tc.get("scored_symbols") or 0),
        "shortlist": eligible_n,
    }

    return {
        "status": "ok",
        "generated_at_utc": generated,
        "live_truth": True,
        "summary": True,
        "alpaca_connected": alpaca.configured,
        "account": {
            "connected": alpaca.configured,
            "equity": account.equity if account else None,
            "cash": account.cash if account else None,
            "daily_pl": account.daily_pl if account else None,
        },
        "watchlist": {
            "total": len(crypto.get("symbols") or []) + len(stocks.get("symbols") or []),
            "crypto": crypto,
            "stocks": stocks,
        },
        "funnel": funnel,
        "eligible_trades": shortlist[:24],
        "shortlist": shortlist[:24],
        "why_zero_shortlist": zero_reason if not shortlist else None,
        "block_breakdown": breakdown,
        "control": _control_from_truth(truth),
        "positions": [
            {
                "symbol": p.symbol,
                "qty": p.qty,
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
        "ai_cockpit_message": _cockpit_narrative(
            {"funnel": funnel, "why_zero_shortlist": zero_reason},
            truth,
            shortlist,
            {"universe_ranking": {}},
        ),
        "ai_brain": {
            "active_lessons": lesson_total,
            "recent_lessons": [
                {"title": r.title, "memory_type": r.memory_type, "symbol": r.symbol}
                for r in lesson_rows
            ],
        },
    }


def build_cockpit(session: Session) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    generated = datetime.utcnow().isoformat() + "Z"

    alpaca = AlpacaAdapter(session)
    if alpaca.configured:
        alpaca.sync_account_cached(force=True)
        alpaca.sync_positions_cached(force=True)

    from app.services.scan_limits import scan_limit

    wl = live_full_watchlist(session, force=True)
    funnel = live_funnel(session, cfg)
    truth = product_truth(session, cfg)
    eval_limit = scan_limit(cfg, "universe.max_scanned_symbols_per_cycle", 0)
    scores = score_active_universe(session, cfg, limit=eval_limit)
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
        "scores": score_rows[:48],
        "eligible_trades": passed[:24],
        "passed_count": len(passed),
        "weights": weights,
        "control": _control_from_truth(truth),
        "summary": False,
        "alpaca_connected": alpaca.configured,
        "positions": [
            {
                "symbol": p.symbol,
                "qty": p.qty,
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
        f"Watchlist funnel: {f.get('available', 0)} available → {f.get('eligible', f.get('shortlist', 0))} eligible for entry.",
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
