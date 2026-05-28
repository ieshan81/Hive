"""
Micro-capital allocator (~$200 paper account).

Discrete allocation:
- ~60% cash reserve
- ~40% deployable
- max 2 open positions
- max 20% equity per position
- paper trade target $20–$40 (never below Alpaca $10 + buffer)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PositionSnapshot
from app.services.engine_config import cfg_get


def _zero_or_negative_means_unlimited(value: Any) -> bool:
    try:
        return int(value) <= 0
    except (TypeError, ValueError):
        return False


@dataclass
class AllocationDecision:
    allowed: bool
    notional_usd: float
    reason_code: Optional[str]
    human_reason: Optional[str]
    evidence: dict[str, Any]


class MicroCapAllocator:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config

    def compute_entry_notional(
        self,
        *,
        equity: float,
        buying_power: float,
        symbol: str,
        open_positions: list,
        pending_notional: float = 0.0,
    ) -> AllocationDecision:
        reserve_pct = float(cfg_get(self.config, "portfolio.reserve_cash_pct", 60.0)) / 100.0
        raw_max_positions = cfg_get(self.config, "portfolio.max_concurrent_positions", 2)
        max_positions_unlimited = _zero_or_negative_means_unlimited(raw_max_positions)
        max_positions = 0 if max_positions_unlimited else int(raw_max_positions)
        max_sym_pct = float(cfg_get(self.config, "risk.max_exposure_per_symbol_pct", 20.0)) / 100.0
        deploy_pct = 1.0 - reserve_pct
        alpaca_min = float(cfg_get(self.config, "execution.alpaca_crypto_min_notional_usd", 10.0))
        buffer = float(cfg_get(self.config, "execution.alpaca_min_notional_buffer_usd", 0.5))
        min_trade = alpaca_min + buffer
        target_min = float(cfg_get(self.config, "allocator.paper_trade_notional_min_usd", 20.0))
        target_max = float(cfg_get(self.config, "allocator.paper_trade_notional_max_usd", 40.0))

        open_count = len([p for p in open_positions if float(getattr(p, "qty", 0) or 0) > 0])
        deployable = max(0.0, equity * deploy_pct - pending_notional)
        sym_cap = equity * max_sym_pct
        bp_cap = max(0.0, buying_power - equity * reserve_pct)

        evidence = {
            "equity": round(equity, 2),
            "deployable_usd": round(deployable, 2),
            "symbol_cap_usd": round(sym_cap, 2),
            "buying_power_cap_usd": round(bp_cap, 2),
            "open_positions": open_count,
            "max_open_positions": None if max_positions_unlimited else max_positions,
            "max_open_positions_policy": "unlimited" if max_positions_unlimited else "capped",
            "alpaca_min_notional": min_trade,
            "target_range_usd": [target_min, target_max],
        }

        if not max_positions_unlimited and open_count >= max_positions:
            return AllocationDecision(
                False, 0, "ALLOCATOR_MAX_POSITIONS", f"Already at max {max_positions} open positions", evidence
            )

        raw = min(deployable, sym_cap, bp_cap, target_max)
        if raw < min_trade:
            return AllocationDecision(
                False,
                0,
                "ALLOCATOR_INSUFFICIENT_CAPITAL",
                f"Available ${raw:.2f} cannot meet Alpaca minimum ${min_trade:.2f}",
                evidence,
            )

        notional = max(min_trade, min(raw, target_max))
        if notional < target_min and raw >= target_min:
            notional = min(raw, target_max)

        # Block duplicate symbol with pending submit
        sym_norm = symbol.upper()
        pending = self.session.exec(
            select(ExecutionLog).where(
                ExecutionLog.symbol == symbol,
                ExecutionLog.status.in_(
                    ("paper_order_submitted", "paper_order_pending", "paper_order_partially_filled")
                ),
            )
        ).first()
        if pending:
            return AllocationDecision(
                False, 0, "ALLOCATOR_DUPLICATE_SYMBOL", f"Pending order exists for {symbol}", evidence
            )

        return AllocationDecision(True, round(notional, 2), None, None, {**evidence, "notional_usd": notional})
