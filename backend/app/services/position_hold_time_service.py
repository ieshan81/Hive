"""True position hold time — never use broker sync as entry unless fallback."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import OrderRecord, PositionEnrichedState, PositionSnapshot, TradeRecord
from app.services.symbol_normalize import broker_symbol, display_symbol, symbol_variants, symbols_match


HOLD_SOURCES = (
    "order_filled_at",
    "order_submitted_at",
    "trade_opened_at",
    "position_state_opened_at",
    "broker_opened_at",
    "sync_fallback",
)


def resolve_entry_time(
    session: Session,
    symbol: str,
    *,
    pos: Optional[PositionSnapshot] = None,
    broker_opened_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Priority: filled_at → submitted_at → trade.opened_at → enriched opened_at → broker opened_at → synced_at (warn).
    """
    variants = symbol_variants(symbol)
    broker_sym = broker_symbol(symbol)
    display_sym = display_symbol(symbol)

    if pos is None:
        for v in variants:
            pos = session.exec(
                select(PositionSnapshot).where(PositionSnapshot.symbol == v, PositionSnapshot.qty > 0)
            ).first()
            if pos:
                break

    order = _latest_order(session, variants)
    trade = _latest_open_trade(session, variants)
    enriched = _enriched_state(session, variants)

    entry_dt: Optional[datetime] = None
    hold_time_source = "unknown"
    hold_time_warning: Optional[str] = None

    if order and order.filled_at:
        entry_dt = _naive_utc(order.filled_at)
        hold_time_source = "order_filled_at"
    elif order and order.submitted_at:
        entry_dt = _naive_utc(order.submitted_at)
        hold_time_source = "order_submitted_at"
        hold_time_warning = "filled_at_missing_used_submitted_at"
    elif trade and trade.opened_at:
        entry_dt = _naive_utc(trade.opened_at)
        hold_time_source = "trade_opened_at"
    elif enriched and enriched.get("opened_at"):
        entry_dt = _parse_iso(enriched["opened_at"])
        if entry_dt:
            hold_time_source = "position_state_opened_at"
    elif broker_opened_at:
        entry_dt = _naive_utc(broker_opened_at)
        hold_time_source = "broker_opened_at"
    elif pos and pos.synced_at:
        entry_dt = _naive_utc(pos.synced_at)
        hold_time_source = "sync_fallback"
        hold_time_warning = "no_order_fill_time_using_broker_sync_not_true_entry"

    true_hold_minutes = 0.0
    if entry_dt:
        true_hold_minutes = max(0.0, (datetime.utcnow() - entry_dt).total_seconds() / 60.0)

    original_filled_at = None
    if order and order.filled_at:
        original_filled_at = order.filled_at.isoformat() + "Z"
    original_entry_time = entry_dt.isoformat() + "Z" if entry_dt else None
    broker_synced_at = pos.synced_at.isoformat() + "Z" if pos and pos.synced_at else None

    return {
        "symbol": symbol,
        "broker_symbol": broker_sym,
        "display_symbol": display_sym,
        "original_filled_at": original_filled_at,
        "original_entry_time": original_entry_time,
        "broker_synced_at": broker_synced_at,
        "true_hold_minutes": round(true_hold_minutes, 2),
        "hold_time_source": hold_time_source,
        "hold_time_warning": hold_time_warning,
        "order_id": order.id if order else None,
        "signal_id": order.signal_id if order else (enriched or {}).get("signal_id"),
        "broker_order_id": order.alpaca_order_id if order else (enriched or {}).get("broker_order_id"),
        "client_order_id": order.broker_client_order_id if order else (enriched or {}).get("client_order_id"),
        "data_source": "Broker Position / Position State",
        "source_table": "orders" if order else ("position_enriched_states" if enriched else "position_snapshots"),
        "source_endpoint": "/api/positions/state",
    }


def build_position_truth(session: Session, symbol: str, pos: Optional[PositionSnapshot] = None) -> dict[str, Any]:
    """Full broker position truth for drawer and audits."""
    from app.services.position_state_service import build_enriched_state

    if pos is None:
        for v in symbol_variants(symbol):
            pos = session.exec(
                select(PositionSnapshot).where(PositionSnapshot.symbol == v, PositionSnapshot.qty > 0)
            ).first()
            if pos:
                break
    if not pos:
        return {"symbol": symbol, "status": "no_position"}

    sym = pos.symbol
    hold = resolve_entry_time(session, sym, pos=pos)
    enriched = build_enriched_state(
        session,
        sym,
        {
            "qty": pos.qty,
            "avg_entry_price": pos.avg_entry_price,
            "current_price": pos.current_price,
            "market_value": pos.market_value,
            "unrealized_pl": pos.unrealized_pl,
            "unrealized_pl_pct": pos.unrealized_pl_pct,
            "side": pos.side,
            "synced_at": pos.synced_at,
        },
    )
    enriched.update(hold)
    enriched["broker_mode"] = "paper"
    enriched["live_trading_locked"] = True
    enriched["alpaca_base_url_type"] = "paper"
    return enriched


def audit_all_open_positions(session: Session) -> dict[str, Any]:
    rows = list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
    audits = [build_position_truth(session, p.symbol, p) for p in rows]
    return {
        "status": "ok",
        "audited_at": datetime.utcnow().isoformat() + "Z",
        "positions": audits,
        "count": len(audits),
    }


def _latest_order(session: Session, variants: list[str]) -> Optional[OrderRecord]:
    rows = list(session.exec(select(OrderRecord).order_by(OrderRecord.submitted_at.desc())).all())
    matched = [r for r in rows if any(symbols_match(r.symbol, v) for v in variants)]
    if not matched:
        return None
    return max(matched, key=lambda r: r.filled_at or r.submitted_at or datetime.min)


def _latest_open_trade(session: Session, variants: list[str]) -> Optional[TradeRecord]:
    rows = list(
        session.exec(
            select(TradeRecord).where(TradeRecord.status == "open").order_by(TradeRecord.opened_at.desc())
        ).all()
    )
    for r in rows:
        if any(symbols_match(r.symbol, v) for v in variants):
            return r
    return None


def _enriched_state(session: Session, variants: list[str]) -> Optional[dict]:
    for row in session.exec(select(PositionEnrichedState)).all():
        if any(symbols_match(row.broker_symbol, v) for v in variants):
            return row.state_json or {}
    return None


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.replace(tzinfo=None)
    return dt


def _parse_iso(val: str) -> Optional[datetime]:
    try:
        s = val.replace("Z", "").split("+")[0]
        return datetime.fromisoformat(s)
    except Exception:
        return None
