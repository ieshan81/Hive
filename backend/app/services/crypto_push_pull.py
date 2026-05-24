"""Crypto push-pull strategy — fast in/out momentum for crypto night session."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session

from app.database import PositionSnapshot, StrategySignal
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services import quant_math


STRATEGY_NAME = "crypto_push_pull"
MEME_SYMBOLS = {"DOGE/USD", "DOGEUSD", "SHIB/USD", "SHIBUSD"}


def broker_position_qty(positions: list[PositionSnapshot], symbol: str) -> float:
    target = normalize_crypto_symbol(symbol).replace("/", "")
    for p in positions:
        ps = normalize_crypto_symbol(p.symbol).replace("/", "")
        if ps == target or p.symbol == symbol:
            return float(p.qty or 0)
    return 0.0


def _bar_price_at(bars: list[dict], hours_ago: int) -> Optional[float]:
    if len(bars) < hours_ago + 1:
        return None
    return bars[-(hours_ago + 1)]["close"]


def _momentum(current: float, past: Optional[float]) -> Optional[float]:
    if past is None or past <= 0:
        return None
    return (current - past) / past


class CryptoPushPullStrategy:
    def __init__(self, session: Session, config: dict, alpaca: AlpacaAdapter):
        self.session = session
        self.config = config
        self.alpaca = alpaca
        self.pp = config.get("crypto_push_pull", {})
        self.cycle_run_id: Optional[str] = None

    def evaluate(
        self,
        symbol: str,
        *,
        positions: list[PositionSnapshot],
        liquidity_score: Optional[float] = None,
        spread_pct: Optional[float] = None,
        eligibility: str = "eligible",
    ) -> Optional[StrategySignal]:
        max_spread = float(self.config.get("max_spread_pct", 0.005))
        max_vol = float(self.pp.get("max_volatility", 0.10))
        edge_min = float(self.pp.get("edge_min_over_cost", 1.2))
        stop_pct = float(self.pp.get("stop_loss_pct", 0.02))
        tp_pct = float(self.pp.get("take_profit_pct", 0.03))

        quote_sym = normalize_crypto_symbol(symbol)
        quote = self.alpaca.get_quote(symbol, "crypto")
        if quote is None or quote.get("bid") is None or quote.get("ask") is None:
            return None

        spread = spread_pct if spread_pct is not None else quote.get("spread_pct")
        if spread is None or spread > max_spread:
            return None

        elig = (eligibility or "eligible").lower()
        if elig not in ("eligible", "caution"):
            return None

        bars = self.alpaca.get_crypto_bars(quote_sym, timeframe="1Hour", limit=16)
        if len(bars) < 8:
            return None

        current = quote.get("mid") or (quote["bid"] + quote["ask"]) / 2
        m1 = _momentum(current, _bar_price_at(bars, 1))
        m3 = _momentum(current, _bar_price_at(bars, 3))
        m6 = _momentum(current, _bar_price_at(bars, 6))
        m12 = _momentum(current, _bar_price_at(bars, 12))

        closes = [b["close"] for b in bars]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        vol = quant_math.volatility(returns) or 0.0

        pos_qty = broker_position_qty(positions, symbol)
        has_position = pos_qty > 0

        slippage = float(self.config.get("slippage_assumption_pct", 0.001))
        fee = float(self.config.get("fee_assumption_pct", 0.0))
        est_cost = quant_math.estimated_total_cost(spread or 0, slippage, fee)

        weighted_momentum = 0.0
        weights = {"1h": 0.35, "3h": 0.30, "6h": 0.20, "12h": 0.15}
        vals = {"1h": m1, "3h": m3, "6h": m6, "12h": m12}
        wsum = 0.0
        for k, w in weights.items():
            if vals[k] is not None:
                weighted_momentum += w * vals[k]
                wsum += w
        if wsum > 0:
            weighted_momentum /= wsum

        edge_score = weighted_momentum - est_cost * edge_min
        spread_quality = max(0.0, 1.0 - (spread or 0) / max_spread)
        vol_filter = 1.0 if 0 < vol <= max_vol else 0.3
        liq_factor = 1.0 if liquidity_score is None or liquidity_score >= 40 else 0.5
        confidence = round(
            min(1.0, max(0.0, 0.4 * min(1.0, abs(weighted_momentum) / 0.02) + 0.25 * spread_quality + 0.2 * vol_filter + 0.15 * liq_factor)),
            4,
        )

        base_meta: dict[str, Any] = {
            "momentum_1h": m1,
            "momentum_3h": m3,
            "momentum_6h": m6,
            "momentum_12h": m12,
            "weighted_momentum": weighted_momentum,
            "expected_move_pct": abs(weighted_momentum) * 100.0,
            "edge_score": edge_score,
            "estimated_cost": est_cost,
            "volatility": vol,
            "spread_pct": spread,
            "current_price": current,
            "broker_position_qty": pos_qty,
        }

        # C — observation: negative momentum, no position
        if not has_position and weighted_momentum < 0:
            return self._save(
                symbol=symbol,
                signal="observe",
                side="hold",
                signal_type="observation",
                status="observation",
                strength=abs(weighted_momentum),
                confidence=confidence,
                metadata={
                    **base_meta,
                    "entry_reason": None,
                    "invalidation_reason": None,
                    "reason": "observe_downtrend_no_position",
                    "expected_hold_time": None,
                },
            )

        # B — exit only with broker position
        if has_position:
            exit_reason = None
            if m1 is not None and m1 < -float(self.pp.get("momentum_threshold_1h", 0.004)):
                exit_reason = "momentum_reversal"
            elif spread and spread > max_spread * 0.8:
                exit_reason = "spread_risk_worsened"
            elif vol > max_vol:
                exit_reason = "volatility_too_high"
            if exit_reason:
                entry = quote.get("bid") or current
                return self._save(
                    symbol=symbol,
                    signal="sell",
                    side="sell",
                    signal_type="exit",
                    status="generated",
                    strength=min(1.0, abs(weighted_momentum) / 0.02),
                    confidence=confidence,
                    stop_loss=entry * (1 + stop_pct),
                    take_profit=entry * (1 - tp_pct),
                    metadata={
                        **base_meta,
                        "entry_reason": exit_reason,
                        "invalidation_reason": None,
                        "expected_hold_time": f"max {self.pp.get('max_hold_hours', 12)}h",
                        "exit_qty_cap": pos_qty,
                    },
                )
            return None

        # A — entry BUY
        thresh = float(self.pp.get("momentum_threshold_1h", 0.004))
        if m1 is None or m1 < thresh or weighted_momentum <= 0:
            return None
        if vol > max_vol:
            return None
        if edge_score <= 0:
            return None
        if liquidity_score is not None and liquidity_score < self.config.get("min_liquidity_score", 40):
            return None

        entry = quote.get("ask") or current
        return self._save(
            symbol=symbol,
            signal="buy",
            side="buy",
            signal_type="entry",
            status="generated",
            strength=min(1.0, edge_score / 0.02),
            confidence=confidence,
            stop_loss=entry * (1 - stop_pct),
            take_profit=entry * (1 + tp_pct),
            metadata={
                **base_meta,
                "entry_reason": f"Positive push-pull momentum edge={edge_score:.4f}",
                "invalidation_reason": None,
                "expected_hold_time": f"{self.pp.get('max_hold_hours', 12)}h",
                "expected_edge": edge_score,
            },
        )

    def _save(
        self,
        *,
        symbol: str,
        signal: str,
        side: str,
        signal_type: str,
        status: str,
        strength: float,
        confidence: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> StrategySignal:
        from app.database import StrategySignal

        row = StrategySignal(
            strategy=STRATEGY_NAME,
            symbol=symbol,
            asset_class="crypto",
            signal=signal,
            side=side,
            strength=strength,
            confidence=confidence,
            status=status,
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
