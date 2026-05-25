"""Technical candle analysis — annotated levels with reason, timeframe, confidence, invalidation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService


def _closes(bars: list) -> list[float]:
    out = []
    for b in bars:
        c = getattr(b, "close", None) if hasattr(b, "close") else b.get("close")
        if c is not None:
            out.append(float(c))
    return out


def _highs(bars: list) -> list[float]:
    return [float(getattr(b, "high", b.get("high", 0)) if hasattr(b, "high") else b["high"]) for b in bars]


def _lows(bars: list) -> list[float]:
    return [float(getattr(b, "low", b.get("low", 0)) if hasattr(b, "low") else b["low"]) for b in bars]


def _volumes(bars: list) -> list[float]:
    return [float(getattr(b, "volume", b.get("volume", 0)) if hasattr(b, "volume") else b["volume"]) for b in bars]


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(closes: list[float]) -> dict[str, Optional[float]]:
    if len(closes) < 26:
        return {"macd": None, "signal": None, "histogram": None}
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if not ema12 or not ema26:
        return {"macd": None, "signal": None, "histogram": None}
    macd_line = [a - b for a, b in zip(ema12[-len(ema26) :], ema26)]
    signal = _ema(macd_line, 9)
    if not signal:
        return {"macd": macd_line[-1] if macd_line else None, "signal": None, "histogram": None}
    hist = macd_line[-1] - signal[-1]
    return {"macd": macd_line[-1], "signal": signal[-1], "histogram": hist}


def _atr(bars: list, period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h = _highs([bars[i]])[0]
        l = _lows([bars[i]])[0]
        pc = _closes([bars[i - 1]])[0]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if trs else None


def _bollinger(closes: list[float], period: int = 20, std_mult: float = 2.0) -> dict[str, Optional[float]]:
    if len(closes) < period:
        return {"upper": None, "middle": None, "lower": None}
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(var)
    return {"upper": mid + std_mult * std, "middle": mid, "lower": mid - std_mult * std}


class TechnicalCandleAnalysisService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.hist = HistoricalDataService(session, self.config)

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "technical_candle_analysis",
            "indicators": ["RSI", "MACD", "ATR", "Bollinger", "support", "resistance", "VWAP"],
            "annotation_required_fields": [
                "reason",
                "timeframe",
                "confidence",
                "invalidation_level",
                "source_bars",
            ],
            "no_fake_lines": True,
        }

    def analyze(self, symbol: str, timeframe: str = "5Min", limit: int = 120) -> dict[str, Any]:
        norm = normalize_crypto_symbol(symbol)
        bars, meta = self.hist.get_bars(norm, timeframe=timeframe, min_rows=min(30, limit // 2))
        if not bars:
            return {"status": "empty", "message": "No bars available", "symbol": norm, "timeframe": timeframe}

        closes = _closes(bars)
        highs = _highs(bars)
        lows = _lows(bars)
        last = closes[-1] if closes else 0
        rsi = _rsi(closes)
        macd = _macd(closes)
        atr = _atr(bars)
        bb = _bollinger(closes)
        vwap = self._vwap(bars)

        annotations: list[dict] = []
        support = min(lows[-20:]) if len(lows) >= 20 else min(lows) if lows else last
        resistance = max(highs[-20:]) if len(highs) >= 20 else max(highs) if highs else last

        annotations.append(
            self._ann(
                "support",
                support,
                "Recent swing low cluster from last 20 bars",
                timeframe,
                min(0.95, 0.5 + len(bars) / 200),
                resistance * 1.02,
                len(bars),
            )
        )
        annotations.append(
            self._ann(
                "resistance",
                resistance,
                "Recent swing high cluster from last 20 bars",
                timeframe,
                min(0.95, 0.5 + len(bars) / 200),
                support * 0.98,
                len(bars),
            )
        )
        if vwap:
            annotations.append(
                self._ann(
                    "vwap",
                    vwap,
                    "Volume-weighted average price over loaded bars",
                    timeframe,
                    0.75,
                    support * 0.97,
                    len(bars),
                )
            )
        if bb.get("upper") and bb.get("lower"):
            annotations.append(
                self._ann(
                    "bollinger_upper",
                    bb["upper"],
                    "Bollinger upper band (20, 2σ)",
                    timeframe,
                    0.7,
                    bb["middle"] or last,
                    20,
                )
            )
            annotations.append(
                self._ann(
                    "bollinger_lower",
                    bb["lower"],
                    "Bollinger lower band (20, 2σ)",
                    timeframe,
                    0.7,
                    bb["middle"] or last,
                    20,
                )
            )

        patterns = self._patterns(bars, closes, highs, lows, timeframe)

        return {
            "status": "ok",
            "symbol": norm,
            "display_symbol": symbol,
            "timeframe": timeframe,
            "bar_count": len(bars),
            "last_price": last,
            "indicators": {
                "rsi_14": rsi,
                "macd": macd,
                "atr_14": atr,
                "bollinger": bb,
                "vwap": vwap,
            },
            "annotations": annotations,
            "patterns": patterns,
            "trendlines": patterns.get("trendlines", []),
            "meta": {
                "analyzed_at": datetime.utcnow().isoformat() + "Z",
                "source": meta.get("source", "historical_bars"),
                "bar_meta": meta,
            },
        }

    def _ann(
        self,
        kind: str,
        level: float,
        reason: str,
        timeframe: str,
        confidence: float,
        invalidation: float,
        source_bars: int,
    ) -> dict:
        return {
            "type": kind,
            "level": round(level, 8),
            "reason": reason,
            "timeframe": timeframe,
            "confidence": round(confidence, 3),
            "invalidation_level": round(invalidation, 8),
            "source_bars": source_bars,
        }

    def _vwap(self, bars: list) -> Optional[float]:
        num = 0.0
        den = 0.0
        for b in bars:
            h = float(getattr(b, "high", b.get("high", 0)) if hasattr(b, "high") else b["high"])
            l = float(getattr(b, "low", b.get("low", 0)) if hasattr(b, "low") else b["low"])
            c = float(getattr(b, "close", b.get("close", 0)) if hasattr(b, "close") else b["close"])
            v = float(getattr(b, "volume", b.get("volume", 0)) if hasattr(b, "volume") else b["volume"])
            tp = (h + l + c) / 3
            num += tp * v
            den += v
        return num / den if den > 0 else None

    def _patterns(
        self, bars: list, closes: list[float], highs: list[float], lows: list[float], tf: str
    ) -> dict[str, Any]:
        patterns: list[dict] = []
        trendlines: list[dict] = []
        if len(closes) < 5:
            return {"patterns": patterns, "trendlines": trendlines}

        last = closes[-1]
        prev = closes[-2]
        body = abs(last - prev)
        wick_up = highs[-1] - max(last, prev)
        wick_dn = min(last, prev) - lows[-1]

        if wick_up > body * 2 and wick_up > wick_dn:
            patterns.append(
                {
                    "pattern": "wick_rejection_upper",
                    "reason": "Upper wick > 2× body — rejection at highs",
                    "timeframe": tf,
                    "confidence": 0.72,
                    "invalidation_level": highs[-1] * 1.01,
                    "source_bars": len(bars),
                }
            )
        if body > 0 and (closes[-1] - closes[-4]) / closes[-4] > 0.02:
            patterns.append(
                {
                    "pattern": "breakout_up",
                    "reason": "Close broke above 4-bar range (>2%)",
                    "timeframe": tf,
                    "confidence": 0.68,
                    "invalidation_level": closes[-4],
                    "source_bars": len(bars),
                }
            )
        if len(closes) >= 10 and closes[-1] < closes[-5] < closes[-10]:
            trendlines.append(
                {
                    "type": "trendline_down",
                    "reason": "Lower highs over last 10 bars",
                    "timeframe": tf,
                    "confidence": 0.65,
                    "invalidation_level": highs[-1] * 1.02,
                    "source_bars": 10,
                }
            )

        return {"patterns": patterns, "trendlines": trendlines}
