"""Chart overlays — entries, exits, SL/TP from cage execution + signals."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, StrategySignal


def chart_context(
    session: Session,
    symbol: str,
    *,
    limit: int = 40,
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    since = datetime.utcnow() - timedelta(days=14)

    logs = list(
        session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.symbol == sym)
            .where(ExecutionLog.submitted_at >= since)
            .order_by(ExecutionLog.submitted_at.desc())
            .limit(limit)
        ).all()
    )
    signals = list(
        session.exec(
            select(StrategySignal)
            .where(StrategySignal.symbol == sym)
            .where(StrategySignal.created_at >= since)
            .order_by(StrategySignal.created_at.desc())
            .limit(limit)
        ).all()
    )

    markers: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []

    for log in logs:
        if not log.submitted_at:
            continue
        t = int(log.submitted_at.timestamp())
        side = (log.side or "").lower()
        is_buy = side in ("buy", "long")
        markers.append(
            {
                "time": t,
                "position": "belowBar" if is_buy else "aboveBar",
                "color": "#00FF66" if is_buy else "#EF4444",
                "shape": "arrowUp" if is_buy else "arrowDown",
                "text": f"{side.upper()} {log.status or 'paper'}",
            }
        )
        if log.reference_price and log.reference_price > 0:
            levels.append(
                {
                    "price": float(log.reference_price),
                    "color": "#00dbe9",
                    "title": f"Entry {side}",
                    "lineStyle": 2,
                }
            )

    for sig in signals[:8]:
        if sig.stop_loss and sig.stop_loss > 0:
            levels.append(
                {
                    "price": float(sig.stop_loss),
                    "color": "#EF4444",
                    "title": "SL (cage)",
                    "lineStyle": 0,
                }
            )
        if sig.take_profit and sig.take_profit > 0:
            levels.append(
                {
                    "price": float(sig.take_profit),
                    "color": "#00FF66",
                    "title": "TP (cage)",
                    "lineStyle": 0,
                }
            )
        if sig.created_at and sig.signal_type and "entry" in (sig.signal_type or "").lower():
            markers.append(
                {
                    "time": int(sig.created_at.timestamp()),
                    "position": "belowBar",
                    "color": "#a78bfa",
                    "shape": "circle",
                    "text": f"AI signal {sig.signal_type}",
                }
            )

    narrative_parts = []
    if markers:
        narrative_parts.append(f"{len(markers)} trade/signal markers on chart.")
    if levels:
        narrative_parts.append(f"{len(levels)} SL/TP levels from formula cage.")
    if not narrative_parts:
        narrative_parts.append("No paper trades on this symbol yet — markers appear after agent cycles.")

    return {
        "status": "ok",
        "symbol": sym,
        "markers": markers[:30],
        "price_lines": levels[:12],
        "ai_narrative": " ".join(narrative_parts),
        "execution_count": len(logs),
        "signal_count": len(signals),
    }
