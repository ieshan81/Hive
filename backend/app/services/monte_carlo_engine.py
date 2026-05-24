"""Monte Carlo from real logged trade outcomes only."""

from __future__ import annotations

import random
from typing import Optional

from sqlmodel import Session, select

from app.database import MonteCarloResult, TradeRecord


class MonteCarloEngine:
    MIN_TRADES = 10

    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config

    def run(self, starting_capital: Optional[float] = None) -> MonteCarloResult:
        target = self.config.get("monte_carlo_target_capital", 500.0)
        sims = self.config.get("monte_carlo_simulations", 1000)

        closed = self.session.exec(
            select(TradeRecord).where(
                TradeRecord.status == "closed",
                TradeRecord.return_pct.isnot(None),
            )
        ).all()

        if len(closed) < self.MIN_TRADES:
            result = MonteCarloResult(
                starting_capital=starting_capital or 0,
                target_capital=target,
                status="unavailable",
                warning="Not enough real trade data for Monte Carlo",
            )
            self.session.add(result)
            self.session.commit()
            self.session.refresh(result)
            return result

        returns = [t.return_pct for t in closed if t.return_pct is not None]
        start = starting_capital or (closed[0].entry_price * closed[0].quantity if closed else 200)

        final_values: list[float] = []
        max_drawdowns: list[float] = []
        median_path: list[float] = [start]
        paths: list[list[float]] = []

        horizon = 240
        for _ in range(sims):
            equity = start
            peak = start
            path = [equity]
            max_dd = 0.0
            for _day in range(horizon):
                sampled = random.choice(returns)
                equity = equity * (1 + sampled)
                peak = max(peak, equity)
                dd = (peak - equity) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)
                path.append(equity)
            final_values.append(equity)
            max_drawdowns.append(max_dd)
            paths.append(path)

        for day in range(1, horizon + 1):
            day_vals = sorted(p[day] for p in paths)
            median_path.append(day_vals[len(day_vals) // 2])

        final_values.sort()
        prob_target = sum(1 for v in final_values if v >= target) / len(final_values)
        prob_dd = sum(1 for d in max_drawdowns if d >= 0.15) / len(max_drawdowns)
        ruin = sum(1 for v in final_values if v < start * 0.5) / len(final_values)

        result = MonteCarloResult(
            starting_capital=start,
            target_capital=target,
            simulation_count=sims,
            median_path=median_path,
            best_case=final_values[int(len(final_values) * 0.9)],
            worst_case=final_values[int(len(final_values) * 0.1)],
            probability_target=prob_target * 100,
            probability_drawdown=prob_dd * 100,
            risk_of_ruin=ruin * 100,
            assumptions=f"Based on {len(returns)} real closed trades, {horizon}-step bootstrap",
            warning="Projections based on historical trade outcomes — not guarantees",
            status="completed",
        )
        self.session.add(result)
        self.session.commit()
        self.session.refresh(result)
        return result

    def get_latest(self) -> MonteCarloResult | None:
        return self.session.exec(
            select(MonteCarloResult).order_by(MonteCarloResult.created_at.desc())
        ).first()
