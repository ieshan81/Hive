"""Rolling Pearson correlation on hourly log returns."""

from __future__ import annotations

import math
from typing import Any, Optional

from app.database import PositionSnapshot
from app.services.alpaca_adapter import normalize_crypto_symbol


def _log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            out.append(math.log(closes[i] / closes[i - 1]))
    return out


def pearson(a: list[float], b: list[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def correlation_penalty_for_candidate(
    alpaca,
    symbol: str,
    open_positions: list[PositionSnapshot],
    *,
    threshold: float = 0.70,
    lookback_hours: int = 720,
) -> tuple[float, dict[str, Any]]:
    if not alpaca or not open_positions:
        return 0.0, {"correlation_status": "no_open_positions"}

    limit = min(lookback_hours, 200)
    bars_a = alpaca.get_crypto_bars(normalize_crypto_symbol(symbol), timeframe="1Hour", limit=limit)
    if len(bars_a) < 20:
        return 0.0, {"correlation_status": "insufficient_data", "bars": len(bars_a)}

    closes_a = [b["close"] for b in bars_a]
    ret_a = _log_returns(closes_a)
    max_corr: Optional[float] = None
    paired_with: Optional[str] = None

    for pos in open_positions:
        if (pos.qty or 0) <= 0:
            continue
        sym_b = normalize_crypto_symbol(pos.symbol)
        if sym_b == normalize_crypto_symbol(symbol):
            continue
        bars_b = alpaca.get_crypto_bars(sym_b, timeframe="1Hour", limit=limit)
        if len(bars_b) < 20:
            continue
        ret_b = _log_returns([b["close"] for b in bars_b])
        c = pearson(ret_a, ret_b)
        if c is not None and (max_corr is None or abs(c) > abs(max_corr)):
            max_corr = c
            paired_with = pos.symbol

    if max_corr is None:
        return 0.0, {"correlation_status": "insufficient_data"}

    ev: dict[str, Any] = {
        "correlation_status": "ok",
        "max_correlation": max_corr,
        "paired_with": paired_with,
        "threshold": threshold,
    }
    if abs(max_corr) > threshold:
        ev["correlation_status"] = "blocked"
        ev["human_reason"] = f"Correlation {max_corr:.2f} with {paired_with} exceeds {threshold}"
        return 1.0, ev
    return max(0.0, abs(max_corr) - 0.5), ev
