"""Meme volatility / momentum spike detection — manipulation risk protection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import HistoricalBar, MemeSpikeEvaluation, PositionSnapshot
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager


MEME_SYMBOLS = frozenset({"DOGE/USD", "DOGEUSD", "SHIB/USD", "SHIBUSD"})


def _bar_field(bar: Any, field: str, default: float = 0.0) -> float:
    if isinstance(bar, dict):
        return float(bar.get(field, default))
    return float(getattr(bar, field, default))


class MemeVolatilitySpikeDetector:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)
        self.cfg = (self.config.get("aggressive_paper_learning") or {}) | (
            self.config.get("meme_spike_detector") or {}
        )

    def evaluate_symbol(self, symbol: str, timeframes: Optional[list[str]] = None) -> dict[str, Any]:
        sym = symbol.upper()
        tier = self._tier(sym)
        bars_1m = self._bars(sym, "1Min", 30)
        bars_5m = self._bars(sym, "5Min", 24)
        bars_15m = self._bars(sym, "15Min", 16)
        tf_status = {
            "1Min": bool(bars_1m),
            "5Min": bool(bars_5m),
            "15Min": bool(bars_15m),
        }
        if not any(tf_status.values()):
            return {
                "symbol": sym,
                "detector_version": "v2",
                "status": "data_unavailable",
                "message": "Short-timeframe bar data unavailable — no spike score computed.",
                "timeframes_used": ["1Min", "5Min", "15Min"],
                "timeframe_data_available": tf_status,
                "spike_detected": False,
                "suggested_action": "observe_only",
                "confidence": 0.0,
            }
        quote = self.alpaca.get_quote(normalize_crypto_symbol(sym), "crypto") or {}

        price_1m = self._pct_change(bars_1m, 1)
        price_5m = self._pct_change(bars_5m, 1)
        price_15m = self._pct_change(bars_15m, 1) if bars_15m else self._pct_change(bars_5m, 3)
        vol_spike = self._volume_spike_ratio(bars_5m)
        spread_pct = quote.get("spread_pct") or 0.0
        wick = self._wick_size(bars_1m)

        manipulation = "low"
        reason_codes: list[str] = []
        if abs(price_5m) > 0.08 or abs(price_1m) > 0.04:
            manipulation = "medium"
            reason_codes.append("fast_price_move")
        if vol_spike > 3.0:
            manipulation = "high" if manipulation != "extreme" else manipulation
            reason_codes.append("volume_spike")
        if spread_pct > float(self.config.get("max_spread_pct", 0.005)) * 2:
            manipulation = "high"
            reason_codes.append("spread_wide")
        if wick > 0.03 and abs(price_1m) > 0.02:
            manipulation = "extreme"
            reason_codes.append("wick_reversal")

        spike_detected = manipulation in ("high", "extreme") or abs(price_5m) > 0.05
        allow_tiny = bool(self.cfg.get("allow_tiny_training_on_spike", False))
        if manipulation in ("high", "extreme") and not allow_tiny:
            action = "block"
        elif manipulation == "medium":
            action = "observe_only"
        elif tier != "MEME_SUPPORTED":
            action = "observe_only"
        else:
            action = "tiny_training_entry"

        from app.services.lesson_memory_service import LessonMemoryService

        if action == "block":
            import json

            LessonMemoryService(self.session, self.config).upsert_lesson(
                memory_type="meme_spike_block_memory",
                title=f"Meme spike block: {sym}",
                summary=f"Spike v2 blocked entry: {', '.join(reason_codes)}",
                detailed_lesson=json.dumps(
                    {
                        "manipulation": manipulation,
                        "price_change_15m": price_15m,
                        "reason_codes": reason_codes,
                    }
                ),
                symbol=sym,
                source="meme_spike_v2",
                pattern_key=f"spike_v2|block|{sym}|{datetime.utcnow().date()}",
            )

        out = {
            "symbol": sym,
            "detector_version": "v2",
            "tier": tier,
            "timeframes_used": ["1Min", "5Min", "15Min"],
            "timeframe_data_available": tf_status,
            "spike_detected": spike_detected,
            "momentum_quality": "strong" if price_5m > 0.02 else "weak" if price_5m < -0.02 else "neutral",
            "manipulation_risk": manipulation,
            "entry_quality": "poor" if manipulation in ("high", "extreme") else "fair",
            "suggested_action": action,
            "reason_codes": reason_codes,
            "metrics": {
                "price_change_1m": price_1m,
                "price_change_5m": price_5m,
                "price_change_15m": price_15m,
                "volume_spike_ratio": vol_spike,
                "spread_pct": spread_pct,
                "wick_size": wick,
            },
            "suggested_max_hold_minutes": int(self.cfg.get("meme_coin_max_hold_minutes", 240)),
            "confidence": 0.7 if bars_5m else 0.4,
        }
        self.session.add(
            MemeSpikeEvaluation(
                symbol=sym,
                spike_detected=spike_detected,
                momentum_quality=out["momentum_quality"],
                manipulation_risk=manipulation,
                entry_quality=out["entry_quality"],
                suggested_action=action,
                reason_codes_json=reason_codes,
                metrics_json=out["metrics"],
            )
        )
        return out

    def evaluate_many(self, symbols: list[str], timeframes: Optional[list[str]] = None) -> dict[str, Any]:
        results = [self.evaluate_symbol(s, timeframes) for s in symbols]
        return {"status": "ok", "evaluations": results}

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.session.exec(
            select(MemeSpikeEvaluation).order_by(MemeSpikeEvaluation.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "spike_detected": r.spike_detected,
                "manipulation_risk": r.manipulation_risk,
                "suggested_action": r.suggested_action,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]

    def status(self) -> dict[str, Any]:
        open_meme = [
            p
            for p in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()
            if "DOGE" in (p.symbol or "").upper() or "SHIB" in (p.symbol or "").upper()
        ]
        return {
            "status": "ok",
            "detector_version": "v2",
            "meme_symbols": list(MEME_SYMBOLS),
            "open_meme_positions": len(open_meme),
            "block_pump_dump_risk": bool(self.cfg.get("block_pump_dump_risk", True)),
            "timeframes": ["1Min", "5Min", "15Min"],
        }

    def _tier(self, symbol: str) -> str:
        if symbol in MEME_SYMBOLS or "DOGE" in symbol or "SHIB" in symbol:
            return "MEME_SUPPORTED"
        if "BTC" in symbol or "ETH" in symbol or "SOL" in symbol:
            return "MAJOR_CRYPTO"
        return "WATCH_ONLY"

    def _bars(self, symbol: str, timeframe: str, limit: int) -> list:
        norm = normalize_crypto_symbol(symbol)
        rows = list(
            self.session.exec(
                select(HistoricalBar)
                .where(HistoricalBar.symbol == norm, HistoricalBar.timeframe == timeframe)
                .order_by(HistoricalBar.timestamp.desc())
                .limit(limit)
            ).all()
        )
        if rows:
            return list(reversed(rows))
        try:
            fetched = self.alpaca.get_crypto_bars(norm, timeframe, limit=limit)
            return fetched or []
        except Exception:
            return []

    def _pct_change(self, bars: list, lookback: int) -> float:
        if len(bars) < lookback + 1:
            return 0.0
        c0 = _bar_field(bars[-lookback - 1], "close")
        c1 = _bar_field(bars[-1], "close")
        if c0 <= 0:
            return 0.0
        return (c1 - c0) / c0

    def _volume_spike_ratio(self, bars: list) -> float:
        if len(bars) < 5:
            return 1.0
        vols = [_bar_field(b, "volume") for b in bars[-10:]]
        avg = sum(vols[:-1]) / max(len(vols) - 1, 1)
        return vols[-1] / avg if avg > 0 else 1.0

    def _wick_size(self, bars: list) -> float:
        if not bars:
            return 0.0
        b = bars[-1]
        h = _bar_field(b, "high")
        l = _bar_field(b, "low")
        c = _bar_field(b, "close")
        if c <= 0:
            return 0.0
        return (h - l) / c
