"""Portfolio broker vs local reconciliation — operator-facing truth."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PositionSnapshot
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.cockpit_chart_service import chart_context
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import get_latest_reset_epoch
from app.services.positions_tab_service import current_positions


WARNING_INCOMPLETE_LOCAL = (
    "Broker position exists, but local order history is incomplete. Broker truth is being used."
)
NOTE_POST_RESET = (
    "Broker position synced after reset — local journal fills in as new paper orders execute."
)


def portfolio_reconciliation(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    epoch = get_latest_reset_epoch(session)
    post_reset = bool(epoch and epoch.get("reset_epoch_id"))
    alpaca = AlpacaAdapter(session)
    alpaca.sync_account()
    alpaca.sync_positions()

    broker_positions = current_positions(session)
    broker_rows = []
    warnings: list[str] = []
    for pos in broker_positions:
        sym = pos.get("symbol") or ""
        local_orders = list(
            session.exec(
                select(OrderRecord)
                .where(OrderRecord.symbol == sym)
                .order_by(OrderRecord.submitted_at.desc())
                .limit(5)
            ).all()
        )
        local_exec = list(
            session.exec(
                select(ExecutionLog)
                .where(ExecutionLog.symbol == sym)
                .order_by(ExecutionLog.created_at.desc())
                .limit(5)
            ).all()
        )
        local_incomplete = (pos.get("qty") or 0) > 0 and not local_orders and not local_exec
        if local_incomplete and not post_reset:
            warnings.append(WARNING_INCOMPLETE_LOCAL)

        pos_snap = session.exec(
            select(PositionSnapshot).where(PositionSnapshot.symbol == sym).limit(1)
        ).first()
        ctx = chart_context(session, sym, last_close=pos.get("current_price"))
        entry_price = pos.get("avg_entry_price") or (pos_snap.avg_entry_price if pos_snap else None)

        broker_rows.append(
            {
                "symbol": sym,
                "qty": pos.get("qty"),
                "avg_entry": entry_price,
                "current_price": pos.get("current_price"),
                "market_value": pos.get("market_value"),
                "unrealized_pl": pos.get("unrealized_pl"),
                "unrealized_pl_pct": pos.get("unrealized_pl_pct"),
                "synced_at": pos.get("opened_at"),
                "source": "alpaca_paper",
                "chart_context": {
                    "markers": ctx.get("markers") or [],
                    "price_lines": ctx.get("price_lines") or [],
                    "overlay_summary": ctx.get("overlay_summary") or {},
                    "ai_narrative": ctx.get("ai_narrative"),
                },
                "local_orders": [
                    {
                        "id": o.id,
                        "status": o.status,
                        "side": o.side,
                        "qty": o.qty,
                        "alpaca_order_id": o.alpaca_order_id,
                        "submitted_at": o.submitted_at.isoformat() + "Z" if o.submitted_at else None,
                    }
                    for o in local_orders
                ],
                "local_execution_logs": [
                    {
                        "id": e.id,
                        "status": e.status,
                        "reject_reason": e.reject_reason,
                        "broker_order_id": e.broker_order_id,
                        "created_at": e.created_at.isoformat() + "Z" if e.created_at else None,
                    }
                    for e in local_exec
                ],
                "local_history_incomplete": local_incomplete and not post_reset,
                "local_history_note": NOTE_POST_RESET if local_incomplete and post_reset else None,
                "strategy_link": None,
            }
        )

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "broker_truth": {
            "positions": broker_rows,
            "position_count": len(broker_rows),
            "btc_position": next((p for p in broker_rows if "BTC" in str(p.get("symbol", "")).upper()), None),
            "synced_at": datetime.utcnow().isoformat() + "Z",
        },
        "local_truth": {
            "reset_epoch": epoch,
            "order_count": len(session.exec(select(OrderRecord)).all()),
            "execution_log_count": len(session.exec(select(ExecutionLog)).all()),
        },
        "reconciliation_warning": (
            WARNING_INCOMPLETE_LOCAL
            if any(p.get("local_history_incomplete") for p in broker_rows)
            else None
        ),
        "warnings": list(dict.fromkeys(warnings)),
        "paper_broker_only": True,
        "live_trading_enabled": False,
    }
