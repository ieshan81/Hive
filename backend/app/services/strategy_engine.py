"""MVP strategy families — momentum ORB and mean reversion pairs."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.database import StrategySignal, StrategyState
from app.services.alpaca_adapter import AlpacaAdapter
from app.services import quant_math


class StrategyEngine:
    STRATEGIES = ["momentum_orb", "mean_reversion_pairs"]
    ALL_STRATEGIES = ["momentum_orb", "mean_reversion_pairs", "crypto_night_momentum"]

    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)
        self._ensure_states()

    def _ensure_states(self) -> None:
        for name in self.ALL_STRATEGIES:
            existing = self.session.exec(
                select(StrategyState).where(StrategyState.strategy == name)
            ).first()
            if existing is None:
                reason = "Placeholder — not implemented" if name == "crypto_night_momentum" else "Waiting for first cycle"
                self.session.add(
                    StrategyState(
                        strategy=name,
                        status="inactive",
                        status_reason=reason,
                        confidence=0,
                        exposure_pct=0,
                    )
                )
        self.session.commit()

    def set_state(self, strategy: str, status: str, reason: str, strength: float = 0.0) -> None:
        state = self.session.exec(
            select(StrategyState).where(StrategyState.strategy == strategy)
        ).first()
        if state is None:
            state = StrategyState(strategy=strategy)
        state.status = status
        state.status_reason = reason
        state.confidence = round(strength * 100, 2) if strength else state.confidence
        state.updated_at = datetime.utcnow()
        self.session.add(state)
        self.session.commit()

    def run_momentum_orb(self, symbol: str, opening_minutes: Optional[int] = None) -> Optional[StrategySignal]:
        minutes = opening_minutes or self.config.get("opening_range_minutes", 30)
        bars = self.alpaca.get_bars(symbol, timeframe="5Min", limit=80)
        if len(bars) < 10:
            self.set_state("momentum_orb", "inactive", f"No bar data for {symbol}")
            return None

        opening_bars = bars[: max(1, minutes // 5)]
        opening_range_high = max(b["high"] for b in opening_bars)
        opening_range_low = min(b["low"] for b in opening_bars)
        current_price = bars[-1]["close"]

        signal = "hold"
        strength = 0.0
        if current_price > opening_range_high:
            signal = "buy"
            strength = min(1.0, (current_price - opening_range_high) / opening_range_high * 10)
        elif current_price < opening_range_low:
            signal = "sell"
            strength = min(1.0, (opening_range_low - current_price) / opening_range_low * 10)

        row = StrategySignal(
            strategy="momentum_orb",
            symbol=symbol,
            signal=signal,
            strength=strength,
            signal_metadata={
                "opening_range_high": opening_range_high,
                "opening_range_low": opening_range_low,
                "current_price": current_price,
            },
        )
        self.session.add(row)
        if signal != "hold":
            self.set_state("momentum_orb", "active", f"Signal {signal} on {symbol}", strength)
        self.session.commit()
        self.session.refresh(row)
        return row

    def run_mean_reversion_pairs(
        self, symbol_a: str, symbol_b: str, hedge_ratio: float = 1.0
    ) -> Optional[StrategySignal]:
        bars_a = self.alpaca.get_bars(symbol_a, limit=60)
        bars_b = self.alpaca.get_bars(symbol_b, limit=60)
        if len(bars_a) < 20 or len(bars_b) < 20:
            self.set_state("mean_reversion_pairs", "inactive", "Insufficient pair history")
            return None

        n = min(len(bars_a), len(bars_b))
        spreads = [
            quant_math.pairs_spread(bars_a[i]["close"], bars_b[i]["close"], hedge_ratio)
            for i in range(-n, 0)
        ]
        z = quant_math.pairs_z_score(spreads)
        if z is None:
            return None

        entry_z = self.config.get("pairs_z_entry", 2.0)
        exit_z = self.config.get("pairs_z_exit", 0.5)
        signal = "hold"
        strength = 0.0
        if z > entry_z:
            signal = "sell_spread"
            strength = min(1.0, abs(z) / (entry_z * 2))
        elif z < -entry_z:
            signal = "buy_spread"
            strength = min(1.0, abs(z) / (entry_z * 2))
        elif abs(z) < exit_z:
            signal = "close_spread"
            strength = 0.5

        row = StrategySignal(
            strategy="mean_reversion_pairs",
            symbol=f"{symbol_a}/{symbol_b}",
            signal=signal,
            strength=strength,
            signal_metadata={"z_score": z, "hedge_ratio": hedge_ratio, "spread": spreads[-1]},
        )
        self.session.add(row)
        if signal != "hold":
            self.set_state("mean_reversion_pairs", "active", f"Pairs signal {signal}", strength)
        self.session.commit()
        self.session.refresh(row)
        return row

    def get_all_states(self) -> list[StrategyState]:
        return list(self.session.exec(select(StrategyState)).all())
