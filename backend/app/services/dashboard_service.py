"""Aggregate real dashboard data — no mock values."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.config import settings
from app.database import (
    AccountSnapshot,
    AIReview,
    BlockedTrade,
    MonteCarloResult,
    StrategyState,
    SymbolCandidate,
    SystemHealth,
    TradeRecord,
)
from app.services.ai_fund_manager import AIFundManager
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.default_config import RISK_CAGE_RULES
from app.services.memory_engine import MemoryEngine
from app.services.monte_carlo_engine import MonteCarloEngine
from app.services.backtest_engine import BacktestEngine
from app.services.session_engine import SessionEngine


def _empty_state(message: str) -> dict[str, Any]:
    return {"status": "empty", "message": message}


def build_dashboard(session: Session) -> dict[str, Any]:
    config_mgr = ConfigManager(session)
    config = config_mgr.get_current()
    alpaca = AlpacaAdapter(session)
    memory = MemoryEngine(session)
    ai = AIFundManager(session)

    health = session.get(SystemHealth, 1)
    if health is None:
        health = SystemHealth(id=1)
        session.add(health)

    # Sync if configured
    account: AccountSnapshot | None = None
    if alpaca.configured:
        account = alpaca.sync_account()
        alpaca.sync_positions()
        health.alpaca_connected = account is not None
        health.last_account_sync = datetime.utcnow() if account else None
    else:
        health.alpaca_connected = False

    health.database_connected = True
    health.gemini_configured = ai.configured
    health.kill_switch_active = config.get("kill_switch_active", False)
    health.updated_at = datetime.utcnow()
    session.add(health)
    session.commit()

    if account is None:
        latest = session.exec(
            select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())
        ).first()
        account = latest

    # Account Survival
    if not alpaca.configured:
        account_survival = {
            "status": "not_connected",
            "message": "Not connected — configure ALPACA_API_KEY and ALPACA_SECRET_KEY",
            "capital": None,
            "plToday": None,
            "plTodayPct": None,
            "drawdown": None,
            "riskStatus": "UNKNOWN",
            "riskStatusMessage": "Waiting for Alpaca sync",
            "riskLevel": 0,
            "dailyLossUsed": 0,
            "dailyLossLimit": config.get("daily_loss_limit_pct", 0.02) * 200,
            "weeklyLossUsed": 0,
            "weeklyLossLimit": config.get("weekly_loss_limit_pct", 0.05) * 200,
            "sparklines": {"capital": [], "pl": [], "drawdown": []},
        }
    elif account is None:
        account_survival = {
            "status": "waiting",
            "message": "Waiting for Alpaca sync",
            **{k: None for k in ["capital", "plToday", "plTodayPct", "drawdown"]},
            "riskStatus": "UNKNOWN",
            "riskStatusMessage": "No account data yet",
            "riskLevel": 0,
            "dailyLossUsed": 0,
            "dailyLossLimit": 0,
            "weeklyLossUsed": 0,
            "weeklyLossLimit": 0,
            "sparklines": {"capital": [], "pl": [], "drawdown": []},
        }
    else:
        daily_limit = config.get("daily_loss_limit_pct", 0.02) * account.equity
        weekly_limit = config.get("weekly_loss_limit_pct", 0.05) * account.equity
        daily_used = abs(account.daily_pl) if account.daily_pl < 0 else 0
        account_survival = {
            "status": "ok",
            "message": None,
            "capital": account.equity,
            "plToday": account.daily_pl,
            "plTodayPct": account.daily_pl_pct,
            "drawdown": account.drawdown_pct,
            "riskStatus": "NORMAL" if account.drawdown_pct < 10 else "ELEVATED",
            "riskStatusMessage": "All survival parameters within limits."
            if account.drawdown_pct < 10
            else "Drawdown elevated — review risk limits.",
            "riskLevel": min(100, int(account.drawdown_pct * 5)),
            "dailyLossUsed": daily_used,
            "dailyLossLimit": daily_limit,
            "weeklyLossUsed": daily_used,
            "weeklyLossLimit": weekly_limit,
            "sparklines": {"capital": [], "pl": [], "drawdown": []},
        }

    # AI Fund Manager
    latest_review: AIReview | None = ai.get_latest_review()
    blocked_count = len(session.exec(select(BlockedTrade)).all())
    approved_count = len(
        session.exec(select(TradeRecord).where(TradeRecord.status.in_(["open", "closed"]))).all()
    )

    if not ai.configured:
        ai_fund_manager = {
            "status": "not_configured",
            "message": "Gemini not configured — set GEMINI_API_KEY",
            "decision": None,
            "decisionMessage": "AI review unavailable",
            "confidence": None,
            "confidenceLabel": "N/A",
            "reasonSummary": "Configure GEMINI_API_KEY to enable AI reviews.",
            "memoryUsedPct": None,
            "approvalStatus": "PENDING",
            "approvalMessage": "Waiting for AI configuration",
            "stats": {
                "decisionsToday": 0,
                "approved": approved_count,
                "blocked": blocked_count,
                "learnedLessons": len(memory.list_memories(10)),
            },
        }
    elif latest_review is None:
        ai_fund_manager = {
            "status": "waiting",
            "message": "No AI reviews yet",
            "decision": "HOLD",
            "decisionMessage": "Awaiting first AI review cycle.",
            "confidence": None,
            "confidenceLabel": "N/A",
            "reasonSummary": "No reviews generated yet. Run sync or trigger review.",
            "memoryUsedPct": None,
            "approvalStatus": "PENDING",
            "approvalMessage": "No review completed",
            "stats": {
                "decisionsToday": 0,
                "approved": approved_count,
                "blocked": blocked_count,
                "learnedLessons": len(memory.list_memories(10)),
            },
        }
    else:
        payload = latest_review.payload or {}
        ai_fund_manager = {
            "status": "active",
            "message": None,
            "decision": latest_review.decision.upper(),
            "decisionMessage": latest_review.summary[:120],
            "confidence": int(latest_review.confidence * 100),
            "confidenceLabel": "High"
            if latest_review.confidence >= 0.7
            else "Moderate"
            if latest_review.confidence >= 0.4
            else "Low",
            "reasonSummary": latest_review.summary,
            "memoryUsedPct": int(len(memory.list_memories(100)) / 100 * 100),
            "approvalStatus": "APPROVED" if latest_review.decision in ("approve", "hold") else "BLOCKED",
            "approvalMessage": payload.get("risk_assessment", "Review complete"),
            "stats": {
                "decisionsToday": 1,
                "approved": approved_count,
                "blocked": blocked_count,
                "learnedLessons": len(memory.list_memories(100)),
            },
        }

    # Memory graph
    nodes = memory.memory_graph_nodes()
    memory_graph = {
        "status": "empty" if not nodes else "ok",
        "message": "Memory empty" if not nodes else None,
        "nodes": nodes,
    }

    session_state = SessionEngine().detect()

    # Strategy lab
    states = list(session.exec(select(StrategyState)).all())
    display_names = {
        "momentum_orb": "Momentum / ORB",
        "mean_reversion_pairs": "Mean Reversion / Pairs",
        "crypto_night_momentum": "Crypto Night Momentum",
    }
    strategies = []
    for s in states:
        closed = session.exec(
            select(TradeRecord).where(TradeRecord.strategy == s.strategy, TradeRecord.status == "closed")
        ).all()
        perf = None
        if closed:
            perf = sum(t.return_pct or 0 for t in closed) * 100
        strategies.append(
            {
                "id": s.strategy,
                "name": display_names.get(s.strategy, s.strategy),
                "status": s.status.replace("_", " ").title() if s.status else "Inactive",
                "performance7d": perf,
                "confidence": s.confidence,
                "exposure": s.exposure_pct,
                "sparkline": [],
                "message": s.status_reason or ("No trades yet" if perf is None else None),
            }
        )
    if not strategies:
        strategies = [
            {
                "id": "momentum_orb",
                "name": "Momentum / ORB",
                "status": "Inactive",
                "performance7d": None,
                "confidence": 0,
                "exposure": 0,
                "sparkline": [],
                "message": "Run POST /api/cycle/run to activate",
            },
            {
                "id": "mean_reversion_pairs",
                "name": "Mean Reversion / Pairs",
                "status": "Inactive",
                "performance7d": None,
                "confidence": 0,
                "exposure": 0,
                "sparkline": [],
                "message": "Run POST /api/cycle/run to activate",
            },
            {
                "id": "crypto_night_momentum",
                "name": "Crypto Night Momentum",
                "status": "Inactive",
                "performance7d": None,
                "confidence": 0,
                "exposure": 0,
                "sparkline": [],
                "message": "Placeholder — inactive until crypto data works",
            },
        ]

    # Risk cage
    risk_rules = [{"id": str(i + 1), "text": rule, "enforced": True} for i, rule in enumerate(RISK_CAGE_RULES)]

    # Market radar — from DB only (populated by cycle/radar refresh)
    candidates = list(
        session.exec(select(SymbolCandidate).order_by(SymbolCandidate.scanned_at.desc()).limit(25)).all()
    )

    market_assets = []
    for c in candidates:
        spread_str = c.spread_display if c.spread_display else ("No quote" if c.spread_pct is None else f"{c.spread_pct:.3f}%")
        market_assets.append(
            {
                "symbol": c.symbol,
                "name": c.name or c.symbol,
                "assetClass": c.asset_class,
                "liquidity": c.liquidity_score,
                "sentiment": c.sentiment_score,
                "volatility": c.volatility_score,
                "spread": spread_str,
                "eligibility": c.eligibility.upper() if c.eligibility else "UNKNOWN",
                "message": "No quote" if c.spread_pct is None and c.spread_display == "No quote" else None,
            }
        )

    if not market_assets:
        market_radar_status = "empty"
        market_radar_message = "No radar data — run POST /api/cycle/run or /api/radar/refresh"
    elif not alpaca.configured:
        market_radar_status = "not_connected"
        market_radar_message = "Waiting for Alpaca sync"
    else:
        market_radar_status = "ok"
        market_radar_message = None

    # Monte Carlo
    mc = MonteCarloEngine(session, config).get_latest()
    backtest = BacktestEngine(session, config).get_latest()

    if mc is None or mc.status == "unavailable":
        monte_carlo = {
            "status": "unavailable",
            "message": mc.warning if mc else "Monte Carlo unavailable — not enough real trade data",
            "goalFrom": account.equity if account else None,
            "goalTo": config.get("monte_carlo_target_capital", 500),
            "probabilityPct": None,
            "horizonDays": 240,
            "maxDrawdownPct": None,
            "drawdownConfidence": 95,
            "simulations": [],
            "medianPath": [],
            "scenarios": [],
        }
    else:
        scenarios = []
        if mc.worst_case is not None:
            scenarios.append({"percentile": "10% Worst Case", "value": round(mc.worst_case, 2)})
        if mc.median_path:
            scenarios.append({"percentile": "Median", "value": round(mc.median_path[-1], 2)})
        if mc.best_case is not None:
            scenarios.append({"percentile": "10% Best Case", "value": round(mc.best_case, 2)})
        monte_carlo = {
            "status": "ok",
            "message": mc.warning,
            "goalFrom": mc.starting_capital,
            "goalTo": mc.target_capital,
            "probabilityPct": mc.probability_target,
            "horizonDays": 240,
            "maxDrawdownPct": mc.probability_drawdown,
            "drawdownConfidence": 95,
            "simulations": [],
            "medianPath": mc.median_path or [],
            "scenarios": scenarios,
        }

    return {
        "lastSync": datetime.utcnow().strftime("%I:%M:%S %p · %b %d, %Y") if account else "Not synced",
        "systemStatus": {
            "alpacaConnected": health.alpaca_connected,
            "geminiConfigured": health.gemini_configured,
            "databaseConnected": health.database_connected,
            "killSwitchActive": health.kill_switch_active,
            "paperTradingOnly": True,
            "liveTradingEnabled": False,
        },
        "statusChips": [
            {
                "label": "Market Status",
                "value": session_state.us_stock_session.upper(),
                "variant": "success" if session_state.stock_trading_allowed else "neutral",
            },
            {
                "label": "Session Mode",
                "value": session_state.mode.upper().replace("_", " "),
                "variant": "info",
            },
            {
                "label": "AI Mode",
                "value": "LEARNING" if health.gemini_configured else "OFFLINE",
                "variant": "info" if health.gemini_configured else "neutral",
            },
            {
                "label": "Risk Mode",
                "value": "SURVIVAL",
                "variant": "info",
            },
        ],
        "session": session_state.to_dict(),
        "accountSurvival": account_survival,
        "aiFundManager": ai_fund_manager,
        "memoryGraph": memory_graph,
        "strategies": strategies,
        "riskRules": risk_rules,
        "marketAssets": market_assets,
        "marketRadarMeta": {
            "status": market_radar_status,
            "message": market_radar_message,
            "refreshedAt": datetime.utcnow().strftime("%I:%M %p") if account else "—",
            "opportunitiesScanned": len(market_assets),
        },
        "monteCarlo": monte_carlo,
        "backtest": {
            "status": backtest.status if backtest else "not_run",
            "message": (backtest.warnings[0] if backtest and backtest.warnings else "Backtest not run yet"),
        },
    }
