"""Enriched position state — links broker position to order, signal, strategy."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, LessonNode, OrderRecord, PositionSnapshot, StrategySignal
from app.services.symbol_normalize import broker_symbol, display_symbol, symbols_match


def _latest_for_symbol(session: Session, model, symbol: str, order_attr: str = "created_at"):
    """Find latest row matching symbol variants."""
    rows = list(session.exec(select(model)).all())
    matches = [r for r in rows if symbols_match(getattr(r, "symbol", ""), symbol)]
    if not matches:
        return None
    return sorted(matches, key=lambda r: getattr(r, order_attr, None) or datetime.min, reverse=True)[0]


def build_enriched_state(session: Session, broker_sym: str, pos: dict[str, Any]) -> dict[str, Any]:
    display = display_symbol(broker_sym)
    order = _latest_for_symbol(session, OrderRecord, broker_sym)
    if order and order.status in ("filled", "partially_filled", "paper_order_filled"):
        pass
    elif order:
        order = order
    el = _latest_for_symbol(session, ExecutionLog, broker_sym)
    sig = None
    if order and order.signal_id:
        sig = session.get(StrategySignal, order.signal_id)
    if not sig and el and el.signal_id:
        sig = session.get(StrategySignal, el.signal_id)
    if not sig:
        sig = _latest_for_symbol(session, StrategySignal, broker_sym)

    fee_lesson = session.exec(
        select(LessonNode).where(LessonNode.memory_type == "fee_lesson").order_by(LessonNode.created_at.desc())
    ).all()
    fee_lesson = next((m for m in fee_lesson if symbols_match(m.symbol or "", broker_sym)), None)
    ev = (fee_lesson.evidence_json or {}) if fee_lesson else {}

    gross_filled = None
    if order:
        gross_filled = (order.raw_payload or {}).get("filled_qty") or order.qty
    elif el:
        gross_filled = el.filled_qty or el.requested_qty

    broker_qty = pos.get("qty") or ev.get("broker_position_qty")
    fee_qty = ev.get("fee_qty")
    if fee_qty is None and gross_filled and broker_qty:
        fee_qty = float(gross_filled) - float(broker_qty)
    fee_pct = ev.get("difference_pct") or ev.get("fee_pct")

    stop = None
    take_profit = None
    if order:
        stop = order.stop_loss
        take_profit = order.take_profit
    if sig:
        stop = stop or sig.stop_loss
        take_profit = take_profit or sig.take_profit

    meta = (sig.signal_metadata or {}) if sig else {}
    entry_reason = meta.get("entry_reason") or meta.get("reason")
    invalidation = meta.get("invalidation_reason")
    expected_hold = meta.get("expected_hold_time") or "12h"
    max_hold = meta.get("max_hold_hours") or meta.get("max_hold_hours")

    return {
        "broker_symbol": broker_sym,
        "display_symbol": display,
        "symbol": broker_sym,
        "qty": broker_qty,
        "avg_entry_price": pos.get("avg_entry_price"),
        "current_price": pos.get("current_price"),
        "market_value": pos.get("market_value"),
        "unrealized_pl": pos.get("unrealized_pl"),
        "unrealized_pl_pct": pos.get("unrealized_pl_pct"),
        "source": "broker",
        "order_id": order.id if order else None,
        "signal_id": sig.id if sig else (order.signal_id if order else (el.signal_id if el else None)),
        "cycle_run_id": (
            order.cycle_run_id if order else (el.cycle_run_id if el else (sig.cycle_run_id if sig else None))
        ),
        "strategy_name": (getattr(sig, "strategy", None) or getattr(sig, "strategy_name", None)) if sig else None,
        "broker_order_id": order.alpaca_order_id if order else (el.broker_order_id if el else None),
        "client_order_id": order.broker_client_order_id if order else (el.broker_client_order_id if el else None),
        "stop_loss": stop,
        "take_profit": take_profit,
        "expected_hold_time": expected_hold,
        "max_hold_time": max_hold,
        "exit_strategy": "atr_stop_tp" if stop else None,
        "entry_reason": entry_reason,
        "invalidation_reason": invalidation,
        "gross_filled_qty": gross_filled,
        "broker_net_qty": broker_qty,
        "fee_qty": fee_qty,
        "fee_pct": fee_pct,
        "fee_asset": ev.get("fee_asset"),
        "fee_usd_estimate": ev.get("fee_usd_estimate"),
        "fee_adjusted_qty": broker_qty,
        "opened_at": pos.get("opened_at") or (order.filled_at.isoformat() + "Z" if order and order.filled_at else None),
        "last_monitored_at": datetime.utcnow().isoformat() + "Z",
        "monitor_status": pos.get("monitor_status", "active"),
        "exit_status": pos.get("exit_status", "open"),
        "side": pos.get("side", "long"),
    }


def backfill_position_states(session: Session) -> dict[str, Any]:
    from app.services.positions_tab_service import current_positions

    positions = current_positions(session)
    enriched: list[dict[str, Any]] = []
    for pos in positions:
        sym = pos["symbol"]
        state = build_enriched_state(session, sym, pos)
        enriched.append(state)
        _persist_state(session, sym, state)
    return {"status": "ok", "count": len(enriched), "states": enriched}


def _persist_state(session: Session, broker_sym: str, state: dict[str, Any]) -> None:
    from app.database import PositionEnrichedState

    row = session.get(PositionEnrichedState, broker_sym)
    if not row:
        row = PositionEnrichedState(broker_symbol=broker_sym, state_json=state)
    else:
        row.state_json = state
        row.updated_at = datetime.utcnow()
    session.add(row)


def get_enriched_states(session: Session) -> list[dict[str, Any]]:
    from app.database import PositionEnrichedState
    from app.services.positions_tab_service import current_positions

    persisted = {r.broker_symbol: r.state_json for r in session.exec(select(PositionEnrichedState)).all()}
    positions = current_positions(session)
    out = []
    for pos in positions:
        sym = pos["symbol"]
        if sym in persisted and persisted[sym].get("signal_id"):
            out.append(persisted[sym])
        else:
            state = build_enriched_state(session, sym, pos)
            out.append(state)
    return out
