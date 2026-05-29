"""Chart overlays — entries, exits, SL/TP from cage execution + signals."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PositionSnapshot, StrategySignal


def _norm_sym(symbol: str) -> str:
    return symbol.strip().upper()


def _position_for_symbol(session: Session, sym: str) -> Optional[PositionSnapshot]:
    pos = session.exec(select(PositionSnapshot).where(PositionSnapshot.symbol == sym).limit(1)).first()
    if pos:
        return pos
    compact = sym.replace("/", "")
    alts = [compact]
    if compact.endswith("USD") and len(compact) > 3:
        alts.append(f"{compact[:-3]}/{compact[-3:]}")
    return session.exec(select(PositionSnapshot).where(PositionSnapshot.symbol.in_(alts)).limit(1)).first()


def _cluster_markers(markers: list[dict[str, Any]], *, max_count: int = 6) -> list[dict[str, Any]]:
    """Keep recent unique timestamps; drop label text to avoid on-chart overlap."""
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for m in sorted(markers, key=lambda x: int(x.get("time") or 0), reverse=True):
        t = int(m.get("time") or 0)
        if not t or t in seen:
            continue
        seen.add(t)
        out.append({**m, "text": ""})
        if len(out) >= max_count:
            break
    return list(reversed(out))


def _active_price_lines(
    *,
    pos: Optional[PositionSnapshot],
    latest_order: Optional[OrderRecord],
    latest_signal: Optional[StrategySignal],
    last_close: Optional[float] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return at most entry + stop + target lines (no historical clutter)."""
    lines: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    entry: Optional[float] = None
    if pos and (pos.qty or 0) > 0 and pos.avg_entry_price and pos.avg_entry_price > 0:
        entry = float(pos.avg_entry_price)
    elif latest_order and latest_order.filled_avg_price and latest_order.filled_avg_price > 0:
        entry = float(latest_order.filled_avg_price)

    sl: Optional[float] = None
    tp: Optional[float] = None
    if latest_order:
        if latest_order.stop_loss and latest_order.stop_loss > 0:
            sl = float(latest_order.stop_loss)
        if latest_order.take_profit and latest_order.take_profit > 0:
            tp = float(latest_order.take_profit)
    if latest_signal:
        if sl is None and latest_signal.stop_loss and latest_signal.stop_loss > 0:
            sl = float(latest_signal.stop_loss)
        if tp is None and latest_signal.take_profit and latest_signal.take_profit > 0:
            tp = float(latest_signal.take_profit)

    if entry:
        lines.append(
            {
                "price": entry,
                "color": "#00dbe9",
                "title": "Entry",
                "lineStyle": 2,
                "kind": "entry",
                "axisLabelVisible": False,
            }
        )
        summary["entry"] = entry

    if sl:
        lines.append(
            {
                "price": sl,
                "color": "#EF4444",
                "title": "Stop",
                "lineStyle": 0,
                "kind": "sl",
                "axisLabelVisible": False,
            }
        )
        summary["stop_loss"] = sl

    if tp:
        lines.append(
            {
                "price": tp,
                "color": "#00FF66",
                "title": "Target",
                "lineStyle": 0,
                "kind": "tp",
                "axisLabelVisible": False,
            }
        )
        summary["take_profit"] = tp

    ratchet_floor = None
    if latest_signal and isinstance(latest_signal.signal_metadata, dict):
        rs = latest_signal.signal_metadata.get("paper_ratchet_state") or {}
        if isinstance(rs, dict) and rs.get("ratchet_floor"):
            ratchet_floor = float(rs["ratchet_floor"])
    if ratchet_floor and ratchet_floor > 0:
        lines.append(
            {
                "price": ratchet_floor,
                "color": "#f59e0b",
                "title": "Ratchet",
                "lineStyle": 0,
                "kind": "ratchet",
                "axisLabelVisible": False,
            }
        )
        summary["ratchet_floor"] = ratchet_floor

    ref = last_close or (float(pos.current_price) if pos and pos.current_price else None)
    if ref and entry and sl and tp:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        summary["risk_reward"] = round(reward / risk, 2) if risk > 0 else None

    return lines, summary


def chart_context(
    session: Session,
    symbol: str,
    *,
    limit: int = 40,
    last_close: Optional[float] = None,
) -> dict[str, Any]:
    sym = _norm_sym(symbol)
    since = datetime.utcnow() - timedelta(days=14)

    pos = _position_for_symbol(session, sym)
    latest_order = session.exec(
        select(OrderRecord)
        .where(OrderRecord.symbol == sym)
        .order_by(OrderRecord.submitted_at.desc())
        .limit(1)
    ).first()
    latest_signal = session.exec(
        select(StrategySignal)
        .where(StrategySignal.symbol == sym)
        .order_by(StrategySignal.created_at.desc())
        .limit(1)
    ).first()

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

    raw_markers: list[dict[str, Any]] = []
    for log in logs[:12]:
        if not log.submitted_at:
            continue
        side = (log.side or "").lower()
        is_buy = side in ("buy", "long")
        raw_markers.append(
            {
                "time": int(log.submitted_at.timestamp()),
                "position": "belowBar" if is_buy else "aboveBar",
                "color": "#00FF66" if is_buy else "#EF4444",
                "shape": "arrowUp" if is_buy else "arrowDown",
                "kind": "fill",
            }
        )

    for sig in signals[:6]:
        if not sig.created_at:
            continue
        st = (sig.signal_type or "").lower()
        if "entry" not in st and "exit" not in st:
            continue
        is_exit = "exit" in st
        raw_markers.append(
            {
                "time": int(sig.created_at.timestamp()),
                "position": "aboveBar" if is_exit else "belowBar",
                "color": "#a78bfa" if not is_exit else "#f97316",
                "shape": "circle",
                "kind": "ai_exit" if is_exit else "ai_entry",
            }
        )

    markers = _cluster_markers(raw_markers, max_count=6)
    price_lines, overlay_summary = _active_price_lines(
        pos=pos,
        latest_order=latest_order,
        latest_signal=latest_signal,
        last_close=last_close,
    )

    fill_count = sum(1 for m in raw_markers if m.get("kind") == "fill")
    ai_count = sum(1 for m in raw_markers if str(m.get("kind", "")).startswith("ai_"))

    narrative_parts: list[str] = []
    if pos and (pos.qty or 0) > 0:
        narrative_parts.append(f"Open position · qty {pos.qty:.4g}.")
    if overlay_summary.get("entry"):
        narrative_parts.append(f"Entry {overlay_summary['entry']:.4g}.")
    if overlay_summary.get("stop_loss"):
        narrative_parts.append(f"Stop {overlay_summary['stop_loss']:.4g}.")
    if overlay_summary.get("take_profit"):
        narrative_parts.append(f"Target {overlay_summary['take_profit']:.4g}.")
    if overlay_summary.get("risk_reward"):
        narrative_parts.append(f"R:R {overlay_summary['risk_reward']}.")
    if fill_count or ai_count:
        narrative_parts.append(
            f"History: {fill_count} fill marker(s), {ai_count} AI signal(s) — latest {len(markers)} shown without labels."
        )
    if not narrative_parts:
        narrative_parts.append("No active bands yet — overlays appear after the agent places paper trades.")

    return {
        "status": "ok",
        "symbol": sym,
        "markers": markers,
        "price_lines": price_lines,
        "overlay_summary": overlay_summary,
        "ai_narrative": " ".join(narrative_parts),
        "execution_count": len(logs),
        "signal_count": len(signals),
    }
