"""Backtesting foundation — no fake results."""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from app.database import BacktestResult
from app.services.alpaca_adapter import AlpacaAdapter
from app.services import quant_math


class BacktestEngine:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)

    def run_momentum_backtest(
        self,
        symbol: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> BacktestResult:
        if not self.alpaca.configured:
            return self._unavailable("momentum_orb", [symbol], "Alpaca not configured")

        bars = self.alpaca.get_bars(symbol, limit=120)
        if len(bars) < 30:
            return self._unavailable(
                "momentum_orb",
                [symbol],
                "Backtest cannot run: missing data",
            )

        opening_minutes = self.config.get("opening_range_minutes", 30)
        returns: list[float] = []
        for i in range(opening_minutes // 5, len(bars) - 1):
            window = bars[i - opening_minutes // 5 : i]
            if not window:
                continue
            orb_high = max(b["high"] for b in window)
            orb_low = min(b["low"] for b in window)
            price = bars[i]["close"]
            next_price = bars[i + 1]["close"]
            if price > orb_high:
                returns.append(quant_math.return_pct(price, next_price))
            elif price < orb_low:
                returns.append(quant_math.return_pct(next_price, price))

        if not returns:
            return self._unavailable("momentum_orb", [symbol], "Backtest cannot run: no signals generated")

        stats = quant_math.compute_trade_stats(returns)
        slippage = self.config.get("slippage_assumption_pct", 0.001)
        spread = self.config.get("spread_assumption_pct", 0.0005)
        fee = self.config.get("fee_assumption_pct", 0.0)
        cost = quant_math.estimated_total_cost(spread, slippage, fee)
        adjusted_returns = [r - cost for r in returns]

        result = BacktestResult(
            strategy="momentum_orb",
            symbols=[symbol],
            date_start=date_start or bars[0]["timestamp"][:10],
            date_end=date_end or bars[-1]["timestamp"][:10],
            num_trades=stats["num_trades"],
            total_return_pct=sum(adjusted_returns) * 100,
            max_drawdown_pct=(stats["max_drawdown"] or 0) * 100,
            win_rate=stats["win_rate"],
            expectancy=stats["expectancy"],
            profit_factor=stats["profit_factor"],
            slippage_assumption=slippage,
            spread_assumption=spread,
            fee_assumption=fee,
            warnings=[f"Cost adjustment applied: {cost:.4f} per trade"],
            status="completed",
        )
        self.session.add(result)
        self.session.commit()
        self.session.refresh(result)
        return result

    def _unavailable(self, strategy: str, symbols: list, warning: str) -> BacktestResult:
        result = BacktestResult(
            strategy=strategy,
            symbols=symbols,
            status="unavailable",
            warnings=[warning],
        )
        self.session.add(result)
        self.session.commit()
        self.session.refresh(result)
        return result

    def get_latest(self) -> BacktestResult | None:
        from sqlmodel import select

        return self.session.exec(
            select(BacktestResult).order_by(BacktestResult.created_at.desc())
        ).first()
