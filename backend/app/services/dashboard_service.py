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
    ExecutionLog,
    MonteCarloResult,
    PortfolioDecision,
    PositionSnapshot,
    StrategySignal,
    StrategyState,
    SymbolCandidate,
    SystemHealth,
    TradeRecord,
)
from app.services.engine_config import cfg_get, current_promotion_stage
from app.services.kill_switch_service import KillSwitchService
from app.services.promotion_service import PromotionService
from app.services.cooldown_service import CooldownService
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.ai_fund_manager import AIFundManager
from app.services.capital_buckets import compute_buckets
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.default_config import RISK_CAGE_RULES
from app.services.memory_engine import MemoryEngine
from app.services.monte_carlo_engine import MonteCarloEngine
from app.services.backtest_engine import BacktestEngine
from app.services.session_engine import SessionEngine
from app.services.strategy_engine import StrategyEngine
from app.services.order_metrics import order_summary


def _empty_state(message: str) -> dict[str, Any]:
    return {"status": "empty", "message": message}


def _cycle_decision_stats(session: Session, cycle_id: str | None, memory: MemoryEngine) -> dict[str, int]:
    if not cycle_id:
        return {
            "decisionsToday": 0,
            "approved": 0,
            "blocked": 0,
            "deferred": 0,
            "ordersSubmitted": 0,
            "learnedLessons": 0,
        }
    from app.services.decisions_service import latest_summary

    summary = latest_summary(session, cycle_id)
    counts = summary.get("counts") or {}
    return {
        "decisionsToday": counts.get("approved", 0) + counts.get("blocked", 0),
        "approved": counts.get("approved", 0),
        "blocked": counts.get("blocked", 0),
        "deferred": counts.get("deferred", 0),
        "ordersSubmitted": counts.get("orders", 0),
        "learnedLessons": counts.get("lessons", 0),
    }


def build_dashboard(session: Session) -> dict[str, Any]:
    config_mgr = ConfigManager(session)
    config = config_mgr.get_current()
    alpaca = AlpacaAdapter(session)
    memory = MemoryEngine(session)
    ai = AIFundManager(session)
    ai_budget = AIBudgetGuard(session).status()
    StrategyEngine(session, config)

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
            "cash": account.cash,
            "buyingPower": account.buying_power,
            "cryptoBucket": compute_buckets(account.equity, config).crypto_night_bucket,
            "reserveCash": compute_buckets(account.equity, config).reserve_cash_bucket,
            "paperTradingOnly": True,
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

    last_cycle = (health.details or {}).get("last_cycle", {}) if health and health.details else {}
    cycle_id = last_cycle.get("cycle_run_id")
    truth_message = "No tradeable signals this cycle"
    if cycle_id:
        portfolio_decs_early = list(
            session.exec(
                select(PortfolioDecision).where(PortfolioDecision.cycle_run_id == cycle_id)
            ).all()
        )
        signals_early = list(
            session.exec(
                select(StrategySignal).where(StrategySignal.cycle_run_id == cycle_id)
            ).all()
        )
        deferred_early = [d for d in portfolio_decs_early if d.portfolio_status == "portfolio_deferred"]
        approved_no_order_early = [s for s in signals_early if s.status == "approved_no_order"]
        if last_cycle.get("orders_submitted", 0) > 0:
            filled = session.exec(
                select(ExecutionLog)
                .where(
                    ExecutionLog.cycle_run_id == cycle_id,
                    ExecutionLog.status == "paper_order_filled",
                )
                .limit(1)
            ).first()
            sym = filled.symbol if filled else None
            if sym:
                truth_message = f"Paper order submitted this cycle: {sym}"
            else:
                truth_message = (
                    f"Paper order submitted this cycle ({last_cycle.get('orders_submitted')})"
                )
        elif approved_no_order_early:
            meta0 = approved_no_order_early[0].signal_metadata or {}
            code = meta0.get("block_reason_code", "")
            if code == "PAPER_EXECUTION_DISABLED":
                truth_message = "Approved by risk + portfolio Top-1; paper execution disabled"
            else:
                truth_message = f"Approved no order: {code or 'execution policy'}"
        elif deferred_early:
            truth_message = (
                f"Portfolio deferred {len(deferred_early)} signal(s) — "
                f"e.g. {deferred_early[0].portfolio_reason_code}"
            )

    from app.services.ai_learning_memory_service import AILearningMemoryService

    ai_learning_payload = AILearningMemoryService(session, config).learning_directives()

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
            "whatILearned": ai_learning_payload.get("what_i_learned", []),
            "whatIWillAvoid": ai_learning_payload.get("what_i_will_avoid", []),
            "whatIWillTestNext": ai_learning_payload.get("what_i_will_test_next", []),
            "whatChangedBecauseOfMemory": ai_learning_payload.get("what_changed_because_of_memory", []),
            "currentTrainingPosture": ai_learning_payload.get("current_training_posture", {}),
            "currentOpenPositionConcern": ai_learning_payload.get("current_open_position_concern", []),
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
        from app.database import LessonNode

        payload = latest_review.payload or {}
        review_cid = payload.get("cycle_run_id")
        ai_fresh = review_cid == cycle_id if cycle_id else False
        ai_skipped = (latest_review.review_status or "").lower() in ("skipped", "skip")
        if ai_skipped:
            ai_fund_manager = {
                "status": "skipped",
                "message": None,
                "decision": "SKIPPED",
                "decisionMessage": payload.get("skip_reason", "rate_or_daily_limit"),
                "confidence": None,
                "confidenceLabel": "N/A",
                "reasonSummary": f"AI review skipped: {payload.get('skip_reason', 'budget or rate limit')}. Latest deterministic cycle still completed.",
                "memoryUsedPct": None,
                "approvalStatus": "SKIPPED",
                "approvalMessage": truth_message if cycle_id else "AI review skipped this cycle",
                "aiReviewFreshness": "skipped",
                "stats": _cycle_decision_stats(session, cycle_id, memory),
            }
        elif cycle_id and not ai_fresh:
            ai_fund_manager = {
                "status": "stale",
                "message": None,
                "decision": "STALE",
                "decisionMessage": "AI review stale for latest cycle",
                "confidence": None,
                "confidenceLabel": "N/A",
                "reasonSummary": "AI review stale. Latest deterministic cycle still completed.",
                "memoryUsedPct": None,
                "approvalStatus": "STALE",
                "approvalMessage": truth_message,
                "aiReviewFreshness": "stale",
                "stats": _cycle_decision_stats(session, cycle_id, memory),
            }
        else:
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
                "memoryUsedPct": min(
                    100,
                    len(session.exec(select(LessonNode)).all()),
                ),
                "approvalStatus": "CYCLE_TRUTH",
                "approvalMessage": truth_message if cycle_id else "Review complete — AI does not approve trades",
                "aiReviewFreshness": "latest",
                "whatILearned": ai_learning_payload.get("what_i_learned", []),
                "whatIWillAvoid": ai_learning_payload.get("what_i_will_avoid", []),
                "whatIWillTestNext": ai_learning_payload.get("what_i_will_test_next", []),
                "stats": _cycle_decision_stats(session, cycle_id, memory),
            }

    for key, src_key in (
        ("whatILearned", "what_i_learned"),
        ("whatIWillAvoid", "what_i_will_avoid"),
        ("whatIWillTestNext", "what_i_will_test_next"),
        ("whatChangedBecauseOfMemory", "what_changed_because_of_memory"),
        ("currentTrainingPosture", "current_training_posture"),
        ("currentOpenPositionConcern", "current_open_position_concern"),
    ):
        if key not in ai_fund_manager:
            ai_fund_manager[key] = ai_learning_payload.get(src_key, [] if key != "currentTrainingPosture" else {})

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
        "crypto_push_pull": "Crypto Push-Pull",
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
        if c.spread_display:
            spread_str = c.spread_display
        elif c.spread_pct is None:
            spread_str = "No quote"
        else:
            spread_str = f"{c.spread_pct * 100:.3f}%"
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
                "message": c.spread_display if c.spread_display in ("No quote", "Invalid quote") else None,
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

    latest_scan = candidates[0].scanned_at if candidates else health.updated_at
    sync_at = health.last_account_sync or (account.synced_at if account else None)

    portfolio_decs = []
    exec_logs = []
    latest_signals = []
    if cycle_id:
        portfolio_decs = list(
            session.exec(
                select(PortfolioDecision).where(PortfolioDecision.cycle_run_id == cycle_id)
            ).all()
        )
        exec_logs = list(
            session.exec(select(ExecutionLog).where(ExecutionLog.cycle_run_id == cycle_id)).all()
        )
    latest_signals = list(
        session.exec(
            select(StrategySignal)
            .where(StrategySignal.cycle_run_id == cycle_id)
            .order_by(StrategySignal.created_at.desc())
        ).all()
        if cycle_id
        else []
    )

    deferred = [d for d in portfolio_decs if d.portfolio_status == "portfolio_deferred"]
    selected = [d for d in portfolio_decs if d.selected_for_execution]
    blocked_signals = [s for s in latest_signals if s.status in ("blocked", "portfolio_blocked", "risk_blocked")]
    approved_no_order = [s for s in latest_signals if s.status == "approved_no_order"]

    exec_cfg = config.get("execution", {})
    promotion = PromotionService(session, config).status()
    kill = KillSwitchService(session, config).status()
    cooldowns = CooldownService(session, config).list_all()

    from app.services.paper_execution_service import PaperExecutionService
    from app.database import OrderRecord

    paper_status = PaperExecutionService(session).status()
    order_rows = []
    if cycle_id:
        order_rows = list(
            session.exec(select(OrderRecord).where(OrderRecord.cycle_run_id == cycle_id)).all()
        )
    position_rows = list(session.exec(select(PositionSnapshot)).all())
    pos_out = []
    seen_pos = set()
    for p in position_rows:
        if p.symbol in seen_pos or (p.qty or 0) <= 0:
            continue
        seen_pos.add(p.symbol)
        pos_out.append(
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avgEntryPrice": p.avg_entry_price,
                "currentPrice": p.current_price,
                "unrealizedPl": p.unrealized_pl,
                "unrealizedPlPct": p.unrealized_pl_pct,
            }
        )

    ai_meta = last_cycle.get("ai_review_meta") or {}
    if ai_meta.get("ai_review_status") != "success" and ai_fund_manager.get("status") == "active":
        ai_fund_manager = {
            **ai_fund_manager,
            "approvalStatus": "SKIPPED",
            "approvalMessage": ai_meta.get("ai_review_error_message") or "AI review skipped this cycle",
            "decisionMessage": "Deterministic engine only — AI did not run this cycle",
        }

    return {
        "lastSyncAt": (sync_at.isoformat() + "Z") if sync_at else None,
        "lastSync": (sync_at.isoformat() + "Z") if sync_at else "Not synced",
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
            "refreshedAt": (latest_scan.isoformat() + "Z") if latest_scan else None,
            "opportunitiesScanned": len(market_assets),
        },
        "monteCarlo": monte_carlo,
        "backtest": {
            "status": backtest.status if backtest else "not_run",
            "message": (backtest.warnings[0] if backtest and backtest.warnings else "Backtest not run yet"),
        },
        "aiBudget": ai_budget,
        "cryptoPushPull": next(
            (
                {
                    "id": s["id"],
                    "name": s["name"],
                    "status": s["status"],
                    "message": s.get("message"),
                    "confidence": s.get("confidence"),
                }
                for s in strategies
                if s["id"] == "crypto_push_pull"
            ),
            {"id": "crypto_push_pull", "name": "Crypto Push-Pull", "status": "inactive", "message": "No data"},
        ),
        "lab": {
            "backtestStatus": backtest.status if backtest else "not_run",
            "memoryCount": len(memory.list_memories(100)),
            "aiBudgetGuardActive": ai_budget.get("budget_guard_active", False),
        },
        "promotionStage": current_promotion_stage(config),
        "promotion": promotion,
        "portfolioGate": {
            "cycleRunId": cycle_id,
            "rankedCount": len(portfolio_decs),
            "selectedCount": len(selected),
            "deferredCount": len(deferred),
            "topN": int(cfg_get(config, "portfolio.execute_top_n_signals", 1)),
            "decisions": [
                {
                    "symbol": d.symbol,
                    "rank": d.portfolio_rank,
                    "score": d.ranking_score,
                    "status": d.portfolio_status,
                    "reason": d.portfolio_reason_code,
                    "selected": d.selected_for_execution,
                }
                for d in sorted(portfolio_decs, key=lambda x: x.portfolio_rank or 99)
            ],
            "truthMessage": truth_message,
        },
        "executionPolicy": {
            **paper_status,
            "paperOrdersEnabled": paper_status.get("paper_orders_enabled", False),
            "liveOrdersEnabled": paper_status.get("live_orders_enabled", False),
            "brokerMode": paper_status.get("broker_mode_detected"),
            "orderTypeDefault": exec_cfg.get("order_type_default", "marketable_limit_ioc"),
            "maxOrdersPerCycle": exec_cfg.get("max_orders_per_cycle", 1),
            "latestLog": serialize_exec(exec_logs[0]) if exec_logs else None,
            "whyNoOrder": truth_message,
            "selectedSymbol": selected[0].symbol if selected else None,
        },
        "latestCycle": {
            "cycleRunId": cycle_id,
            "riskBlocked": last_cycle.get("blocked", 0),
            "riskApproved": last_cycle.get("risk_approved", 0),
            "portfolioSelected": last_cycle.get("selected_for_execution", 0),
            "portfolioDeferred": last_cycle.get("portfolio_deferred", 0),
            "ordersSubmitted": last_cycle.get("orders_submitted", 0),
            "observations": last_cycle.get("observations", 0),
        },
        "orders": {
            "cycleRunId": cycle_id,
            "count": len(order_rows),
            "items": [
                {
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "status": o.status,
                    "brokerOrderId": o.alpaca_order_id,
                    "clientOrderId": o.broker_client_order_id,
                    "filledAvgPrice": o.filled_avg_price,
                    "orderType": o.order_type,
                }
                for o in order_rows
            ],
        },
        "positionsPanel": {"count": len(pos_out), "items": pos_out},
        "riskCageExtras": {
            "killSwitch": kill,
            "cooldowns": cooldowns,
            "blockedSignalCount": len(blocked_signals),
            "lastCycleBlocked": last_cycle.get("blocked", 0),
            "preflightBlockers": paper_status.get("paper_execution_blockers", []),
            "noAiOrderAuthority": True,
        },
        "orderSummary": order_summary(session),
        "safetyBanner": _safety_banner(session, config, paper_status),
    }


def _safety_banner(session: Session, config: dict, paper_status: dict) -> dict:
    from app.services.broker_reconciliation_service import BrokerReconciliationService
    from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop
    from app.services.live_lock_tripwire import live_lock_tripwire_status

    recon = BrokerReconciliationService(session, config)
    ft = FastCryptoTrainingLoop(session, config).status()
    trip = live_lock_tripwire_status(config)
    open_n = len(list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()))
    ghosts = recon.ghost_position_candidates()
    broker_truth = "Synced" if not ghosts else "Needs Review"
    return {
        "liveTradingLocked": trip.get("live_lock_status") == "locked",
        "trainingMode": "ON" if ft.get("training_mode_enabled") else "OFF",
        "botCanPlaceOrders": "YES" if ft.get("final_can_submit_orders") else "NO",
        "openPositions": open_n,
        "brokerTruth": broker_truth,
        "paperBroker": trip.get("paper_broker", True),
        "plainMessage": ft.get("plain_message")
        or "The bot cannot place new paper orders until Training Mode is enabled.",
    }


def serialize_exec(row: ExecutionLog) -> dict:
    return {
        "eventId": row.event_id,
        "symbol": row.symbol,
        "status": row.status,
        "rejectReason": row.reject_reason,
        "limitPrice": row.limit_price,
        "tif": row.tif,
    }
