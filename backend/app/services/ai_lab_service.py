"""AI lab — compact reviews, deterministic fallback, no fake AI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    AIReview,
    BlockedTrade,
    StrategySignal,
    StrategyState,
)
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.config_manager import ConfigManager


def build_compact_cycle_context(session: Session, cycle_run_id: str, summary: dict) -> dict[str, Any]:
    signals = session.exec(
        select(StrategySignal).where(StrategySignal.cycle_run_id == cycle_run_id)
    ).all()
    blocked = session.exec(
        select(BlockedTrade).where(BlockedTrade.cycle_run_id == cycle_run_id)
    ).all()
    states = session.exec(select(StrategyState)).all()

    return {
        "cycle_run_id": cycle_run_id,
        "session_mode": (summary.get("session") or {}).get("mode"),
        "signals_generated": summary.get("signals_generated", 0),
        "signals_created": summary.get("signals_created", 0),
        "observations": summary.get("observations", 0),
        "blocked": summary.get("blocked", 0),
        "approved": summary.get("approved", 0),
        "positions_count": summary.get("positions_count", 0),
        "signal_summaries": [
            {
                "symbol": s.symbol,
                "strategy": s.strategy,
                "signal_type": s.signal_type,
                "side": s.side,
                "confidence": s.confidence,
                "status": s.status,
            }
            for s in signals[:20]
        ],
        "blocked_summaries": [
            {
                "symbol": b.symbol,
                "code": b.block_reason_code,
                "reason": b.human_reason,
            }
            for b in blocked[:15]
        ],
        "strategy_states": [
            {"strategy": st.strategy, "status": st.status, "reason": st.status_reason}
            for st in states
        ],
    }


def deterministic_cycle_summary(session: Session, cycle_run_id: str, summary: dict) -> dict[str, Any]:
    """System fallback when AI unavailable — not labeled as AI insight."""
    blocked = session.exec(
        select(BlockedTrade).where(BlockedTrade.cycle_run_id == cycle_run_id)
    ).all()
    codes: dict[str, int] = {}
    for b in blocked:
        c = b.block_reason_code or "UNKNOWN"
        codes[c] = codes.get(c, 0) + 1
    top = sorted(codes.items(), key=lambda x: -x[1])[:5]

    text = (
        f"Cycle {cycle_run_id[:8]}: {summary.get('signals_generated', 0)} tradeable signals, "
        f"{summary.get('observations', 0)} observations, {summary.get('blocked', 0)} blocked, "
        f"{summary.get('approved', 0)} approved. "
    )
    if top:
        text += "Top block reasons: " + ", ".join(f"{k}({v})" for k, v in top) + "."
    else:
        text += "No blocks this cycle."

    return {
        "fallback_summary_source": "system",
        "summary": text,
        "block_reason_counts": dict(top),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


class AILabService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.budget = AIBudgetGuard(session)

    def lab_status(self) -> dict[str, Any]:
        from app.database import AIMemory, BacktestResult, AIConfigProposal, AIStrategyNote

        mem_count = len(self.session.exec(select(AIMemory)).all())
        proposals = len(self.session.exec(select(AIConfigProposal)).all())
        notes = len(self.session.exec(select(AIStrategyNote)).all())
        backtests = self.session.exec(select(BacktestResult).order_by(BacktestResult.created_at.desc())).all()

        return {
            "status": "ok",
            "ai_budget": self.budget.status(),
            "memory_count": mem_count,
            "config_proposals_count": proposals,
            "strategy_notes_count": notes,
            "backtest_runs": len(backtests),
            "latest_backtest_status": backtests[0].status if backtests else "not_run",
            "paper_trading_only": True,
        }
