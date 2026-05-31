"""Crash-safe timestamp resolution + portfolio equity curve.

`TradeRecord` / `OrderRecord` rows can carry a ``None`` in any single timestamp
field; naive access (sorting, ``.isoformat()``) then crashes the cockpit and the
diagnostic exports. :func:`safe_record_timestamp` walks a fallback chain and
returns the first present datetime (or ``None``), and :func:`build_equity_curve`
turns closed trades into a portfolio-history series without ever raising on a
missing timestamp.

Pure / read-only. Nothing here mutates records or places orders.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

# Order matters: prefer the most entry-like time, then exit-like, then order times.
TIMESTAMP_FALLBACK_ORDER: tuple[str, ...] = (
    "created_at",
    "opened_at",
    "entry_time",
    "submitted_at",
    "filled_at",
    "closed_at",
    "exit_time",
    "updated_at",
)

_PNL_KEYS: tuple[str, ...] = ("realized_pnl", "realized_pl", "pnl", "net_pnl", "profit")


def _get(rec: Any, key: str) -> Any:
    if isinstance(rec, dict):
        return rec.get(key)
    return getattr(rec, key, None)


def _num(v: Any, fallback: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else fallback
    except (TypeError, ValueError):
        return fallback


def safe_record_timestamp(rec: Any, order: tuple[str, ...] = TIMESTAMP_FALLBACK_ORDER) -> Optional[datetime]:
    """First present datetime across the fallback chain, or None. Never raises.

    Accepts datetimes or ISO strings (``Z`` tolerated); ignores unparseable values."""
    for key in order:
        val = _get(rec, key)
        if isinstance(val, datetime):
            return val
        if isinstance(val, str) and val.strip():
            try:
                return datetime.fromisoformat(val.strip().replace("Z", ""))
            except ValueError:
                continue
    return None


def safe_timestamp_iso(rec: Any) -> Optional[str]:
    ts = safe_record_timestamp(rec)
    return (ts.isoformat() + "Z") if ts else None


def _trade_pnl(rec: Any) -> float:
    for key in _PNL_KEYS:
        val = _get(rec, key)
        if val is not None:
            return _num(val)
    return 0.0


def build_equity_curve(trades: Any, *, starting_equity: float = 0.0) -> dict[str, Any]:
    """Cumulative realized-PnL equity curve from closed trades.

    Rows with no resolvable timestamp are skipped (not dropped silently from the
    count). Returns equity/drawdown series + summary. Never raises on None fields."""
    rows: list[tuple[datetime, float]] = []
    skipped_no_timestamp = 0
    for t in trades or []:
        ts = safe_record_timestamp(t)
        if ts is None:
            skipped_no_timestamp += 1
            continue
        rows.append((ts, _trade_pnl(t)))
    rows.sort(key=lambda r: r[0])

    points: list[dict[str, Any]] = []
    eq = float(starting_equity)
    peak = float(starting_equity)
    max_dd = 0.0
    for ts, pnl in rows:
        eq += pnl
        peak = max(peak, eq)
        dd = ((peak - eq) / peak * 100.0) if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        points.append(
            {
                "t": ts.isoformat() + "Z",
                "equity": round(eq, 2),
                "realized_pnl": round(pnl, 4),
                "drawdown_pct": round(dd, 3),
            }
        )

    return {
        "points": points,
        "point_count": len(points),
        "skipped_no_timestamp": skipped_no_timestamp,
        "start_equity": round(float(starting_equity), 2),
        "current_equity": round(eq, 2),
        "change_usd": round(eq - float(starting_equity), 2),
        "change_pct": round((eq - starting_equity) / starting_equity * 100.0, 3) if starting_equity > 0 else None,
        "max_drawdown_pct": round(max_dd, 3),
    }
