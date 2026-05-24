"""Lab — backtest foundation, honest empty states."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AIMemory, AIStrategyNote, BacktestResult, StrategySignal
from app.services.ai_budget_guard import AIBudgetGuard
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.crypto_push_pull import CryptoPushPullStrategy
from app.services import quant_math


class LabService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)

    def status(self) -> dict[str, Any]:
        guard = AIBudgetGuard(self.session)
        backtests = list(
            self.session.exec(select(BacktestResult).order_by(BacktestResult.created_at.desc()).limit(5)).all()
        )
        memories = len(self.session.exec(select(AIMemory)).all())
        notes = len(self.session.exec(select(AIStrategyNote)).all())
        return {
            "status": "ok",
            "paper_trading_only": True,
            "ai_budget": guard.status(),
            "backtest_count": len(backtests),
            "latest_backtest": self._serialize_backtest(backtests[0]) if backtests else None,
            "memory_count": memories,
            "strategy_notes_count": notes,
            "monte_carlo": {"status": "requires_closed_trades", "message": "Run after real closed trades exist"},
        }

    def list_backtests(self, limit: int = 20) -> list[dict]:
        rows = self.session.exec(
            select(BacktestResult).order_by(BacktestResult.created_at.desc()).limit(limit)
        ).all()
        return [self._serialize_backtest(r) for r in rows]

    def list_strategy_notes(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(
            select(AIStrategyNote).order_by(AIStrategyNote.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id,
                "strategy": r.strategy,
                "note": r.note,
                "source": r.source,
                "cycle_run_id": r.cycle_run_id,
                "created_at": r.created_at.isoformat() + "Z",
            }
            for r in rows
        ]

    def list_memory(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(select(AIMemory).order_by(AIMemory.created_at.desc()).limit(limit)).all()
        return [
            {
                "id": r.id,
                "memory_type": r.memory_type,
                "symbol": r.symbol,
                "strategy": r.strategy,
                "lesson": r.lesson,
                "confidence": r.confidence,
                "created_at": r.created_at.isoformat() + "Z",
            }
            for r in rows
        ]

    def run_crypto_backtest(self, symbol: str = "BTC/USD") -> dict[str, Any]:
        if not self.alpaca.configured:
            row = BacktestResult(
                strategy="crypto_push_pull",
                symbols=[symbol],
                status="error",
                warnings=["Alpaca not configured — cannot fetch historical bars"],
            )
            self.session.add(row)
            self.session.commit()
            return {"status": "error", "message": row.warnings[0], "result": self._serialize_backtest(row)}

        quote_sym = normalize_crypto_symbol(symbol)
        bars = self.alpaca.get_crypto_bars(quote_sym, timeframe="1Hour", limit=200)
        if len(bars) < 30:
            row = BacktestResult(
                strategy="crypto_push_pull",
                symbols=[symbol],
                status="error",
                warnings=[f"Insufficient historical bars ({len(bars)}) for {symbol}"],
            )
            self.session.add(row)
            self.session.commit()
            return {
                "status": "error",
                "message": "Historical data missing or insufficient",
                "result": self._serialize_backtest(row),
            }

        spread = float(self.config.get("spread_assumption_pct", 0.0005))
        slippage = float(self.config.get("slippage_assumption_pct", 0.001))
        fee = float(self.config.get("fee_assumption_pct", 0.0))
        cost = quant_math.estimated_total_cost(spread, slippage, fee)
        thresh = float(self.config.get("crypto_push_pull", {}).get("momentum_threshold_1h", 0.004))

        returns: list[float] = []
        for i in range(13, len(bars) - 1):
            c0 = bars[i]["close"]
            c1 = bars[i - 1]["close"]
            if c1 <= 0:
                continue
            m1 = (c0 - c1) / c1
            if m1 > thresh:
                nxt = bars[i + 1]["close"]
                gross = (nxt - c0) / c0
                returns.append(gross - cost)

        stats = quant_math.compute_trade_stats(returns)
        row = BacktestResult(
            strategy="crypto_push_pull",
            symbols=[symbol],
            date_start=str(bars[0].get("timestamp", ""))[:10] if bars else None,
            date_end=str(bars[-1].get("timestamp", ""))[:10] if bars else None,
            num_trades=stats["num_trades"],
            total_return_pct=sum(returns) * 100 if returns else None,
            max_drawdown_pct=(stats["max_drawdown"] or 0) * 100,
            win_rate=stats["win_rate"],
            expectancy=stats["expectancy"],
            profit_factor=stats["profit_factor"],
            slippage_assumption=slippage,
            spread_assumption=spread,
            fee_assumption=fee,
            status="ok" if stats["num_trades"] > 0 else "empty",
            warnings=[] if stats["num_trades"] > 0 else ["No trades triggered on available bars"],
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return {"status": row.status, "result": self._serialize_backtest(row)}

    def _serialize_backtest(self, row: BacktestResult) -> dict:
        return {
            "id": row.id,
            "strategy": row.strategy,
            "symbols": row.symbols,
            "status": row.status,
            "num_trades": row.num_trades,
            "total_return_pct": row.total_return_pct,
            "max_drawdown_pct": row.max_drawdown_pct,
            "win_rate": row.win_rate,
            "expectancy": row.expectancy,
            "profit_factor": row.profit_factor,
            "warnings": row.warnings,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }
