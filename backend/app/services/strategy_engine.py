"""MVP strategy families — momentum ORB, mean reversion pairs, crypto night momentum."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.database import StrategySignal, StrategyState
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services import quant_math


class StrategyEngine:
    STRATEGIES = ["momentum_orb", "mean_reversion_pairs", "crypto_night_momentum", "crypto_push_pull"]
    ALL_STRATEGIES = ["momentum_orb", "mean_reversion_pairs", "crypto_night_momentum", "crypto_push_pull"]

    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)
        self.cycle_run_id: Optional[str] = None
        self._ensure_states()

    def _ensure_states(self) -> None:
        for name in self.ALL_STRATEGIES:
            existing = self.session.exec(
                select(StrategyState).where(StrategyState.strategy == name)
            ).first()
            if existing is None:
                self.session.add(
                    StrategyState(
                        strategy=name,
                        status="inactive",
                        status_reason="Waiting for first cycle",
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
        if strength > 0:
            state.confidence = round(strength * 100, 2)
        state.updated_at = datetime.utcnow()
        self.session.add(state)
        self.session.commit()

    def _save_signal(
        self,
        *,
        strategy: str,
        symbol: str,
        asset_class: str,
        signal: str,
        side: str,
        strength: float,
        confidence: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        signal_type: str = "entry",
        metadata: Optional[dict] = None,
    ) -> StrategySignal:
        row = StrategySignal(
            strategy=strategy,
            symbol=symbol,
            asset_class=asset_class,
            signal=signal,
            side=side,
            strength=strength,
            confidence=confidence,
            status="generated",
            signal_type=signal_type,
            stop_loss=stop_loss,
            take_profit=take_profit,
            signal_metadata=metadata or {},
            cycle_run_id=self.cycle_run_id,
        )
        self.session.add(row)
        self.session.flush()
        self.session.commit()
        self.session.refresh(row)
        return row

    def run_crypto_night_momentum(self, symbol: str) -> Optional[StrategySignal]:
        lookback = int(self.config.get("crypto_momentum_lookback_bars", 12))
        threshold = float(self.config.get("crypto_momentum_threshold", 0.008))
        max_spread = float(self.config.get("max_spread_pct", 0.005))
        max_vol = float(self.config.get("crypto_momentum_max_volatility", 0.08))

        quote_sym = normalize_crypto_symbol(symbol)
        quote = self.alpaca.get_quote(symbol, "crypto")
        if quote is None or quote.get("bid") is None or quote.get("ask") is None:
            self.set_state("crypto_night_momentum", "inactive", f"Missing price for {symbol}")
            return None

        spread_pct = quote.get("spread_pct")
        spread_display = quote.get("spread_display", "No quote")
        if spread_pct is None:
            self.set_state("crypto_night_momentum", "inactive", f"No quote for {symbol}")
            return None
        if spread_pct > max_spread:
            self.set_state("crypto_night_momentum", "inactive", f"Spread too wide for {symbol} ({spread_display})")
            return None

        bars = self.alpaca.get_crypto_bars(quote_sym, timeframe="1Hour", limit=lookback + 5)
        if len(bars) < lookback:
            self.set_state("crypto_night_momentum", "inactive", f"Missing bars for {symbol}")
            return None

        current_price = quote.get("mid") or (quote["bid"] + quote["ask"]) / 2
        lookback_price = bars[-lookback]["close"]
        if lookback_price <= 0:
            self.set_state("crypto_night_momentum", "inactive", f"Invalid lookback price for {symbol}")
            return None

        return_lookback = (current_price - lookback_price) / lookback_price
        closes = [b["close"] for b in bars]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        vol = quant_math.volatility(returns) or 0.0

        signal = "hold"
        side = "hold"
        if return_lookback > threshold:
            signal, side = "buy", "buy"
        elif return_lookback < -threshold:
            signal, side = "sell", "sell"

        momentum_score = min(1.0, abs(return_lookback) / max(threshold, 1e-6))
        spread_quality = max(0.0, 1.0 - spread_pct / max_spread)
        vol_filter = 1.0 if 0 < vol <= max_vol else 0.4
        session_score = 1.0
        signal_strength = (
            0.40 * momentum_score
            + 0.25 * spread_quality
            + 0.20 * vol_filter
            + 0.15 * session_score
        )
        confidence = round(signal_strength, 4)

        stop_loss = current_price * 0.97 if side == "buy" else (current_price * 1.03 if side == "sell" else None)
        take_profit = current_price * 1.04 if side == "buy" else (current_price * 0.96 if side == "sell" else None)

        metadata = {
            "entry_reason": f"Momentum {return_lookback:.4f} over {lookback}h lookback",
            "invalidation_reason": None if signal != "hold" else "Momentum below threshold",
            "expected_hold_time": "4-12 hours",
            "return_lookback": return_lookback,
            "volatility": vol,
            "spread_pct": spread_pct,
            "spread_display": spread_display,
            "current_price": current_price,
            "lookback_price": lookback_price,
            "momentum_score": momentum_score,
            "spread_quality": spread_quality,
            "vol_filter": vol_filter,
        }

        row = self._save_signal(
            strategy="crypto_night_momentum",
            symbol=symbol,
            asset_class="crypto",
            signal=signal,
            side=side,
            strength=signal_strength,
            confidence=confidence,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata=metadata,
        )

        if signal != "hold":
            self.set_state(
                "crypto_night_momentum",
                "active",
                f"Signal {signal} on {symbol} (strength {signal_strength:.2f})",
                signal_strength,
            )
        return row

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
        side = "hold"
        strength = 0.0
        if current_price > opening_range_high:
            signal, side = "buy", "buy"
            strength = min(1.0, (current_price - opening_range_high) / opening_range_high * 10)
        elif current_price < opening_range_low:
            signal, side = "sell", "sell"
            strength = min(1.0, (opening_range_low - current_price) / opening_range_low * 10)

        stop = current_price * 0.985 if side == "buy" else (current_price * 1.015 if side == "sell" else None)
        row = self._save_signal(
            strategy="momentum_orb",
            symbol=symbol,
            asset_class="stock",
            signal=signal,
            side=side,
            strength=strength,
            confidence=strength,
            stop_loss=stop,
            metadata={
                "entry_reason": f"ORB breakout on {symbol}",
                "invalidation_reason": None if signal != "hold" else "Price inside opening range",
                "expected_hold_time": "intraday",
                "opening_range_high": opening_range_high,
                "opening_range_low": opening_range_low,
                "current_price": current_price,
            },
        )
        if signal != "hold":
            self.set_state("momentum_orb", "active", f"Signal {signal} on {symbol}", strength)
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
        side = "hold"
        strength = 0.0
        if z > entry_z:
            signal, side = "sell_spread", "sell"
            strength = min(1.0, abs(z) / (entry_z * 2))
        elif z < -entry_z:
            signal, side = "buy_spread", "buy"
            strength = min(1.0, abs(z) / (entry_z * 2))
        elif abs(z) < exit_z:
            signal, side = "close_spread", "hold"
            strength = 0.5

        row = self._save_signal(
            strategy="mean_reversion_pairs",
            symbol=f"{symbol_a}/{symbol_b}",
            asset_class="stock",
            signal=signal,
            side=side,
            strength=strength,
            confidence=strength,
            metadata={
                "entry_reason": f"Pairs z-score {z:.3f}",
                "invalidation_reason": None if signal != "hold" else "Z-score inside entry band",
                "expected_hold_time": "multi-day",
                "z_score": z,
                "hedge_ratio": hedge_ratio,
                "spread": spreads[-1],
            },
        )
        if signal != "hold":
            self.set_state("mean_reversion_pairs", "active", f"Pairs signal {signal}", strength)
        return row

    def get_all_states(self) -> list[StrategyState]:
        return list(self.session.exec(select(StrategyState)).all())

    def update_signal_status(self, signal_id: int, status: str, extra: Optional[dict] = None) -> None:
        row = self.session.get(StrategySignal, signal_id)
        if row is None:
            return
        row.status = status
        if extra:
            meta = dict(row.signal_metadata or {})
            meta.update(extra)
            row.signal_metadata = meta
        self.session.add(row)
        self.session.commit()
