"""Positions tab — broker positions, state, history."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, LessonNode, OrderRecord, PositionSnapshot, StrategySignal, TradeRecord
from app.services.alpaca_adapter import AlpacaAdapter


def current_positions(session: Session) -> list[dict[str, Any]]:
    rows = session.exec(
        select(PositionSnapshot).order_by(PositionSnapshot.synced_at.desc())
    ).all()
    seen: set[str] = set()
    out = []
    for p in rows:
        if p.symbol in seen or (p.qty or 0) <= 0:
            continue
        seen.add(p.symbol)
        stop = None
        tp = None
        sig = session.exec(
            select(StrategySignal)
            .where(StrategySignal.symbol == p.symbol)
            .order_by(StrategySignal.created_at.desc())
        ).first()
        if sig:
            stop = sig.stop_loss
            tp = sig.take_profit
        dist_stop = None
        dist_target = None
        if stop and p.current_price:
            dist_stop = abs(p.current_price - stop) / p.current_price * 100
        if tp and p.current_price:
            dist_target = abs(tp - p.current_price) / p.current_price * 100
        out.append(
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "unrealized_pl": p.unrealized_pl,
                "unrealized_pl_pct": p.unrealized_pl_pct,
                "stop_loss": stop,
                "take_profit": tp,
                "distance_to_stop_pct": dist_stop,
                "distance_to_target_pct": dist_target,
                "max_hold_hours": None,
                "opened_at": p.synced_at.isoformat() + "Z" if p.synced_at else None,
                "source": "broker",
                "monitor_status": "active",
                "exit_status": "open",
                "side": p.side,
            }
        )
    return out


def position_states(session: Session) -> list[dict[str, Any]]:
    positions = current_positions(session)
    out = []
    for pos in positions:
        sym = pos["symbol"]
        el = session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.symbol == sym)
            .order_by(ExecutionLog.created_at.desc())
        ).first()
        sig = session.exec(
            select(StrategySignal)
            .where(StrategySignal.symbol == sym)
            .order_by(StrategySignal.created_at.desc())
        ).first()
        fee_lesson = session.exec(
            select(LessonNode).where(
                LessonNode.symbol.in_([sym, sym.replace("USD", "/USD")]),
                LessonNode.memory_type == "fee_lesson",
            ).limit(1)
        ).first()
        ev = (fee_lesson.evidence_json or {}) if fee_lesson else {}
        filled = ev.get("filled_qty")
        broker_qty = ev.get("broker_position_qty") or pos["qty"]
        fee_qty = (float(filled) - float(broker_qty)) if filled and broker_qty else None
        fee_pct = ev.get("difference_pct")
        out.append(
            {
                "symbol": sym,
                "signal_id": sig.id if sig else (el.signal_id if el else None),
                "order_id": el.broker_order_id if el else None,
                "cycle_run_id": el.cycle_run_id if el else None,
                "strategy": sig.strategy if sig else None,
                "entry_reason": (sig.signal_metadata or {}).get("reason") if sig else None,
                "invalidation_reason": None,
                "fee_adjusted_qty": broker_qty,
                "fee_qty": fee_qty,
                "fee_pct": fee_pct,
                "last_monitored_at": pos.get("opened_at"),
                "broker_qty": pos["qty"],
            }
        )
    return out


def trades_history(session: Session, limit: int = 50) -> list[dict[str, Any]]:
    rows = session.exec(
        select(TradeRecord).order_by(TradeRecord.opened_at.desc()).limit(limit)
    ).all()
    out = []
    for t in rows:
        mems = session.exec(
            select(LessonNode).where(LessonNode.symbol == t.symbol).limit(5)
        ).all()
        out.append(
            {
                "trade_id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_time": t.opened_at.isoformat() + "Z" if t.opened_at else None,
                "exit_time": t.closed_at.isoformat() + "Z" if t.closed_at else None,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "qty": t.quantity,
                "realized_pl": t.pl_dollars,
                "fees": None,
                "strategy": t.strategy,
                "reason_opened": None,
                "reason_closed": None,
                "outcome": t.status,
                "return_pct": t.return_pct,
                "linked_memories": [{"id": m.id, "title": m.title} for m in mems],
            }
        )
    return out


def orders_history(session: Session, limit: int = 100) -> list[dict[str, Any]]:
    rows = session.exec(
        select(OrderRecord).order_by(OrderRecord.submitted_at.desc()).limit(limit)
    ).all()
    return [
        {
            "broker_order_id": r.alpaca_order_id,
            "client_order_id": r.broker_client_order_id,
            "symbol": r.symbol,
            "side": r.side,
            "type": r.order_type,
            "tif": (r.raw_payload or {}).get("time_in_force"),
            "requested_qty": r.qty,
            "filled_qty": (r.raw_payload or {}).get("filled_qty"),
            "limit_price": (r.raw_payload or {}).get("limit_price"),
            "filled_avg_price": r.filled_avg_price,
            "status": r.status,
            "submitted_at": r.submitted_at.isoformat() + "Z" if r.submitted_at else None,
            "filled_at": r.filled_at.isoformat() + "Z" if r.filled_at else None,
            "reject_reason": (r.raw_payload or {}).get("reject_reason"),
            "cycle_run_id": r.cycle_run_id,
            "signal_id": r.signal_id,
        }
        for r in rows
    ]


def refresh_positions(session: Session) -> dict[str, Any]:
    alpaca = AlpacaAdapter(session)
    account = alpaca.sync_account()
    positions = alpaca.sync_positions()
    session.commit()
    return {
        "status": "ok",
        "positions_count": len(positions) if positions else 0,
        "equity": account.equity if account else None,
    }
