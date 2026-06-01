"""Recent symbol expectancy guard for controlled paper exploration.

This is not a live-trading risk layer. It is a paper behavior correction: if a
symbol/setup has just produced repeated losses, do not immediately re-enter the
same churn loop unless the cooldown expires or the operator disables the guard.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PaperExperimentOutcome, TradeRecord
from app.services.engine_config import cfg_get
from app.services.order_ledger_service import display_symbol, normalize_symbol


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


class SymbolExpectancyGuardService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def _cfg(self, key: str, default: Any) -> Any:
        return cfg_get(self.config, f"autonomous_paper_learning.recent_expectancy_guard.{key}", default)

    def evaluate(self, symbol: str, strategy_id: Optional[str] = None) -> dict[str, Any]:
        if self._cfg("enabled", True) is False:
            return {"blocked": False, "reason": "disabled"}

        norm = normalize_symbol(symbol)
        now = datetime.utcnow()
        window_hours = float(self._cfg("recent_window_hours", 24) or 24)
        cutoff = now - timedelta(hours=max(1.0, window_hours))
        min_trades = int(self._cfg("min_recent_trades", 2) or 2)
        max_loss = float(self._cfg("max_recent_gross_loss_usd", -0.05) or -0.05)
        min_win_rate = float(self._cfg("min_recent_win_rate", 0.5) or 0.5)
        cooldown_min = int(self._cfg("cooldown_minutes_after_recent_losses", 120) or 120)

        pnl_events: list[dict[str, Any]] = []
        outcomes = self.session.exec(
            select(PaperExperimentOutcome).where(PaperExperimentOutcome.created_at >= cutoff)
        ).all()
        for row in outcomes:
            if normalize_symbol(row.symbol) != norm:
                continue
            if strategy_id and row.strategy_id and str(row.strategy_id) != str(strategy_id):
                continue
            pnl = _num(row.realized_pnl)
            if pnl is None:
                continue
            pnl_events.append({"pnl": pnl, "created_at": row.created_at, "source": "paper_experiment_outcomes"})

        trades = self.session.exec(
            select(TradeRecord).where(TradeRecord.closed_at != None)  # noqa: E711
        ).all()
        for row in trades:
            if row.closed_at and row.closed_at < cutoff:
                continue
            if normalize_symbol(row.symbol) != norm:
                continue
            if strategy_id and row.strategy and str(row.strategy) != str(strategy_id):
                continue
            pnl = _num(row.pl_dollars)
            if pnl is None:
                continue
            pnl_events.append({"pnl": pnl, "created_at": row.closed_at or row.opened_at, "source": "trades"})

        pnl_events.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
        count = len(pnl_events)
        gross = round(sum(float(e["pnl"]) for e in pnl_events), 6) if pnl_events else 0.0
        wins = len([e for e in pnl_events if float(e["pnl"]) > 0])
        win_rate = round(wins / count, 4) if count else None
        latest_loss_at = next((e.get("created_at") for e in pnl_events if float(e["pnl"]) < 0), None)
        cooldown_until = latest_loss_at + timedelta(minutes=cooldown_min) if latest_loss_at else None
        in_cooldown = bool(cooldown_until and cooldown_until > now)
        negative_expectancy = count >= min_trades and (gross <= max_loss or (win_rate is not None and win_rate < min_win_rate))
        blocked = bool(negative_expectancy and in_cooldown)

        return {
            "blocked": blocked,
            "reason": "RECENT_NEGATIVE_EXPECTANCY" if blocked else "ok",
            "symbol": display_symbol(symbol),
            "strategy_id": strategy_id,
            "recent_trade_count": count,
            "recent_gross_pnl": gross if count else None,
            "recent_win_rate": win_rate,
            "recent_window_hours": window_hours,
            "cooldown_minutes": cooldown_min,
            "cooldown_until": cooldown_until.isoformat() + "Z" if cooldown_until else None,
            "min_recent_trades": min_trades,
            "max_recent_gross_loss_usd": max_loss,
            "min_recent_win_rate": min_win_rate,
            "sources": sorted({str(e.get("source")) for e in pnl_events}),
        }
