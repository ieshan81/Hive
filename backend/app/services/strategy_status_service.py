"""Push-pull / candle strategy status — explicit proof of active logic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import StrategyRegistry
from app.services.config_manager import ConfigManager
from app.services.push_pull_engine_service import PushPullEngineService
from app.services.session_engine import SessionEngine


def strategy_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    pp = st.get("push_pull") or {}
    sess = SessionEngine().detect()
    reg = session.exec(
        select(StrategyRegistry).where(StrategyRegistry.strategy_id == "crypto_push_pull_baseline")
    ).first()

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "strategy_name": "Crypto Push-Pull Baseline",
        "strategy_id": "crypto_push_pull_baseline",
        "strategy_version": reg.version if reg and hasattr(reg, "version") else "baseline",
        "active": bool(reg and reg.current_stage not in ("retired", "rejected")),
        "current_stage": reg.current_stage if reg else "unknown",
        "session_aware": True,
        "crypto_active_now": pp.get("crypto_push_pull_active"),
        "stock_active_now": pp.get("stock_push_pull_active"),
        "market_mode": pp.get("market_mode"),
        "signal_formula_summary": (
            "1H Alpaca bars + live quote momentum; push when trend/pullback criteria pass; "
            "cost/spread/stale-quote gates before submit."
        ),
        "entry_triggers": [
            "Eligible strategy in paper_experiment stage",
            "Symbol tradable with funded quote currency",
            "Fresh 5Min bars and quote under max age",
            "Push signal from CryptoPushPullStrategy.evaluate",
            "Positive edge after spread and cost model",
            "Allocator deployable capital available",
            "No duplicate open position on symbol",
        ],
        "entry_blocks": [
            "Open position already exists",
            "Stale bars or stale quote",
            "Spread too wide / negative edge after cost",
            "Quote currency unfunded (USDC/USDT)",
            "Market closed for stocks",
            "Allocator degraded or no deployable capital",
            "Alpaca min notional or precision validation failure",
        ],
        "exit_triggers": [
            "Dynamic take-profit bar (ATR, spread, push quality, edge)",
            "Dynamic stop-loss bar (ATR, spread cushion, signal quality)",
            "Dynamic trailing bar after favorable movement",
            "Invalidation bar when the setup breaks before hard stop",
            "Timeout (push_pull.timeout_minutes)",
            "Stale quote exit",
            "Spread blowout exit",
        ],
        "live_scoring_model": "score_push_pull_setup",
        "scoring_on_live_path": True,
        "candle_logic": {
            "operator_signals_endpoint": "/api/push-pull/signals",
            "technical_analysis": "TechnicalCandleAnalysisService (RSI, patterns, push/pull labels)",
            "trading_cage_scorer": "score_push_pull_setup — primary live scan ranking model",
            "legacy_signal_generator": "CryptoPushPullStrategy.evaluate — validator layer after score rank",
        },
        "ai_influence": "Advisory only via Gemini fund manager reviews — does not auto-trade",
        "sentiment_influence": False,
    }


def candidate_rankings(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    ranked = universe.get("top_candidates") or []
    return {
        "status": st.get("status"),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scoring_model": "persisted_latest_scan",
        "strategy_version": None,
        "top_ranked": ranked[:10],
        "selected_candidate": ranked[0] if ranked else None,
        "rejected_candidates": [],
        "active_count": len(ranked),
        "no_trade_reason_breakdown": {
            b.get("code"): b.get("count") for b in universe.get("top_blockers") or [] if b.get("code")
        },
        "read_model_only": True,
    }


def last_tick_narrative(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    tick = PushPullEngineService(session, cfg).latest_tick()
    plain = tick.get("plain") or ""
    if "fast training" in plain.lower():
        plain = plain.replace("Fast training blocked", "Paper cycle blocked").replace(
            "fast training", "paper learning"
        )
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "tick": tick,
        "narrative": plain or "No tick completed yet.",
    }
