"""Trader Console aggregate service.

This service is read-heavy and paper-only. Manual paper buys still create a
paper experiment decision and execute through TrainingExecutionService, so the
existing deterministic preflight remains the only broker submission path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.database import AIReview, AccountSnapshot, PaperExperimentDecision, PositionSnapshot
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.paper_execution_service import PaperExecutionService
from app.services.push_pull_scoring_service import score_active_universe, score_symbol
from app.services.push_pull_strategy_seed import (
    BASELINE_ID,
    STOCK_BASELINE_ID,
    ensure_crypto_push_pull_baseline,
)
from app.services.symbol_normalize import display_symbol
from app.services.training_execution_service import TrainingExecutionService


_STATUS_CACHE: dict[str, Any] = {}
_STATUS_CACHE_TTL = timedelta(seconds=15)


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _latest_account(session: Session) -> AccountSnapshot | None:
    return session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()


def _latest_decision(session: Session) -> PaperExperimentDecision | None:
    return session.exec(
        select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc())
    ).first()


def _latest_ai_review(session: Session) -> AIReview | None:
    return session.exec(select(AIReview).order_by(AIReview.created_at.desc())).first()


def _account_payload(account: AccountSnapshot | None, adapter: AlpacaAdapter) -> dict[str, Any]:
    if not account:
        return {
            "alpaca_configured": adapter.configured,
            "alpaca_connected": False,
            "cash": None,
            "equity": None,
            "buying_power": None,
            "synced_at": None,
            "message": "Alpaca credentials are missing or no account snapshot has been synced.",
        }
    return {
        "alpaca_configured": adapter.configured,
        "alpaca_connected": bool(adapter.configured),
        "cash": account.cash,
        "equity": account.equity,
        "buying_power": account.buying_power,
        "portfolio_value": account.portfolio_value,
        "daily_pl": account.daily_pl,
        "daily_pl_pct": account.daily_pl_pct,
        "drawdown_pct": account.drawdown_pct,
        "synced_at": account.synced_at.isoformat() + "Z" if account.synced_at else None,
        "rate_limited": bool(getattr(adapter, "broker_sync_rate_limited", False)),
    }


def _decision_payload(decision: PaperExperimentDecision | None) -> dict[str, Any] | None:
    if not decision:
        return None
    return {
        "id": decision.id,
        "symbol": decision.symbol,
        "side": decision.side,
        "decision": decision.decision,
        "reason_code": decision.reason_code,
        "reason_text": decision.reason_text,
        "approved_notional": decision.approved_notional,
        "execution_status": decision.execution_status,
        "created_at": decision.created_at.isoformat() + "Z" if decision.created_at else None,
    }


def _ai_payload(review: AIReview | None) -> dict[str, Any] | None:
    if not review:
        return None
    return {
        "id": review.id,
        "decision": review.decision,
        "review_status": review.review_status,
        "confidence": review.confidence,
        "summary": review.summary,
        "created_at": review.created_at.isoformat() + "Z" if review.created_at else None,
    }


def trader_console_status(session: Session, *, force: bool = False) -> dict[str, Any]:
    cached_at = _STATUS_CACHE.get("cached_at")
    if not force and cached_at and datetime.utcnow() - cached_at < _STATUS_CACHE_TTL:
        payload = dict(_STATUS_CACHE.get("payload") or {})
        payload["cache"] = {"status": "hit", "cached_at": cached_at.isoformat() + "Z"}
        return payload

    cfg = ConfigManager(session).get_current()
    from app.services.scan_limits import scan_limit

    adapter = AlpacaAdapter(session)
    account = adapter.sync_account_cached(force=False) if adapter.configured else _latest_account(session)
    positions = list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
    reviews = OpenPositionReviewService(session, cfg).review_all().get("reviews", [])
    eval_limit = scan_limit(cfg, "universe.max_scanned_symbols_per_cycle", 0)
    scored = score_active_universe(session, cfg, limit=eval_limit)
    scores = scored.get("scores") or []
    eligible = [row for row in scores if row.get("entry_allowed")]
    fresh_count = int(scored.get("fresh_count") or 0)
    latest_decision = _latest_decision(session)
    latest_ai = _latest_ai_review(session)
    paper_status = PaperExecutionService(session).status()
    learning = AggressivePaperLearningService(session).status()
    live = live_lock_status(cfg)

    can_place = (
        bool(cfg_get(cfg, "execution.paper_orders_enabled", False))
        and bool(learning.get("mode_enabled"))
        and bool(is_paper_broker_url())
        and not bool(cfg_get(cfg, "execution.live_orders_enabled", False))
    )

    payload = {
        "status": "ok",
        "generated_at_utc": _now(),
        "schema_version": "trader_console.v1",
        "paper_only": True,
        "paper_broker": is_paper_broker_url(),
        "live_trading_locked": True,
        "live_lock": live,
        "autopilot": {
            "paper_learning": bool(learning.get("mode_enabled")),
            "scheduler_enabled": bool(cfg_get(cfg, "autonomous_paper_learning.scheduler_enabled", False)),
            "can_place_paper_orders_now": can_place,
            "paper_orders_enabled": bool(cfg_get(cfg, "execution.paper_orders_enabled", False)),
            "blockers": learning.get("blockers") or [],
        },
        "account": _account_payload(account, adapter),
        "positions": reviews,
        "open_positions_count": len(positions),
        "eligible_trades": eligible,
        "eligible_count": len(eligible),
        "fresh_count": fresh_count,
        "shortlist": eligible,
        "shortlist_count": len(eligible),
        "scored_symbols": scored.get("symbols_scored", 0),
        "no_trade_reason_breakdown": scored.get("no_trade_reason_breakdown") or {},
        "latest_decision": _decision_payload(latest_decision),
        "latest_ai_nudge": _ai_payload(latest_ai),
        "paper_execution": paper_status,
        "message": (
            f"{len(eligible)} eligible setup(s) — agent trades all that pass gates each cycle."
            if eligible
            else "No symbols passed hard data, edge, and exit-level gates this scan."
        ),
    }
    _STATUS_CACHE["cached_at"] = datetime.utcnow()
    _STATUS_CACHE["payload"] = payload
    return payload


def manual_paper_buy(session: Session, body: dict[str, Any], *, actor: str) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    if not is_paper_broker_url():
        return {"status": "blocked", "reason": "broker_not_paper", "paper_only": True, "live_trading_locked": True}
    if bool(cfg_get(cfg, "execution.live_orders_enabled", False)) or bool(cfg_get(cfg, "live_trading_enabled", False)):
        return {"status": "blocked", "reason": "live_lock", "paper_only": True, "live_trading_locked": True}

    symbol_raw = str((body or {}).get("symbol") or "").strip().upper()
    if not symbol_raw:
        return {"status": "error", "message": "symbol required", "paper_only": True}
    symbol = display_symbol(symbol_raw)
    asset_class = "crypto" if "/" in symbol else "stock"
    strategy_id = BASELINE_ID if asset_class == "crypto" else STOCK_BASELINE_ID

    ensure_crypto_push_pull_baseline(session, cfg)
    score = score_symbol(
        session,
        cfg,
        symbol,
        universe_row={
            "symbol": symbol,
            "status": "Active",
            "asset_type": "Crypto" if asset_class == "crypto" else "Stock",
        },
    )
    if not score.get("entry_allowed"):
        return {
            "status": "blocked",
            "reason": score.get("no_trade_reason") or "paper_exploration_gate",
            "score": score,
            "paper_only": True,
            "live_trading_locked": True,
        }

    signal_meta = {
        **score,
        "manual_operator_request": True,
        "operator_actor": actor,
        "source": "trader_console_manual_buy",
    }
    learning = AggressivePaperLearningService(session)
    decision = learning.evaluate(strategy_id, symbol, side="buy", signal_meta=signal_meta)
    if decision.get("decision") != "approved":
        return {
            **decision,
            "status": "blocked",
            "score": score,
            "paper_only": True,
            "live_trading_locked": True,
        }

    out = TrainingExecutionService(session).execute_approved_decision(int(decision["decision_id"]))
    _STATUS_CACHE.clear()
    return {
        "status": out.get("status", "ok"),
        "decision": decision,
        "execution": out,
        "score": score,
        "execution_path": "TrainingExecutionService -> PaperExecutionService",
        "paper_only": True,
        "live_trading_locked": True,
    }
