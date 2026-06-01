"""Safe repair of stale local open TradeRecord rows when broker truth is flat."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ActivityLog, OrderRecord, PositionSnapshot, TradeRecord
from app.services.exposure_truth_service import ExposureTruthService
from app.services.order_ledger_service import display_symbol, normalize_symbol


FILLED_SELL_STATUSES = {"filled", "paper_order_filled", "paper_order_partially_filled", "partially_filled"}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


class TradeStateRepairService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}
        self.exposure = ExposureTruthService(session, self.config)

    def _broker_truth_available(self) -> bool:
        probe = self.exposure.get_symbol_exposure("BTC/USD")
        return bool((probe.get("evidence") or {}).get("broker_truth_available"))

    def _open_trades_by_symbol(self) -> dict[str, list[TradeRecord]]:
        rows = list(self.session.exec(select(TradeRecord).where(TradeRecord.status == "open")).all())
        grouped: dict[str, list[TradeRecord]] = {}
        for row in rows:
            grouped.setdefault(normalize_symbol(row.symbol), []).append(row)
        return grouped

    def _matching_sell_order(self, trade: TradeRecord) -> Optional[OrderRecord]:
        target = normalize_symbol(trade.symbol)
        rows = list(
            self.session.exec(
                select(OrderRecord)
                .where(OrderRecord.side == "sell")
                .where(OrderRecord.status.in_(list(FILLED_SELL_STATUSES)))
                .order_by(OrderRecord.filled_at.desc(), OrderRecord.submitted_at.desc())
            ).all()
        )
        qty = abs(float(trade.quantity or 0))
        for order in rows:
            if normalize_symbol(order.symbol) != target:
                continue
            if order.filled_at and trade.opened_at and order.filled_at < trade.opened_at:
                continue
            oq = _num(order.qty)
            px = _num(order.filled_avg_price)
            if oq is None or px is None:
                continue
            if qty <= 0 or abs(oq - qty) <= max(1e-8, qty * 0.01):
                return order
        return None

    def _repair_trade(self, trade: TradeRecord, *, dry_run: bool) -> dict[str, Any]:
        sell = self._matching_sell_order(trade)
        action = "mark_broker_reconciled_flat"
        gross_pnl = None
        exit_price = None
        status = "broker_reconciled_flat"
        if sell is not None:
            exit_price = _num(sell.filled_avg_price)
            qty = abs(float(trade.quantity or 0))
            if exit_price is not None and qty > 0:
                gross_pnl = round((exit_price - float(trade.entry_price or 0)) * qty, 8)
                status = "closed_reconciled"
                action = "close_reconciled_from_filled_sell"
        if not dry_run:
            trade.status = status
            trade.closed_at = trade.closed_at or datetime.utcnow()
            if exit_price is not None:
                trade.exit_price = exit_price
                trade.pl_dollars = gross_pnl
                if trade.entry_price:
                    trade.return_pct = ((exit_price - float(trade.entry_price)) / float(trade.entry_price)) * 100.0
            self.session.add(trade)
        return {
            "trade_id": trade.id,
            "symbol": display_symbol(trade.symbol),
            "action": action,
            "new_status": status,
            "matched_exit_order_id": sell.id if sell else None,
            "gross_pnl": gross_pnl,
            "net_pnl": None,
            "no_fake_pnl": sell is None,
        }

    def repair_stale_open_trades_when_broker_flat(
        self,
        *,
        dry_run: bool = True,
        symbols: Optional[list[str]] = None,
        require_no_broker_positions: bool = False,
    ) -> dict[str, Any]:
        if not self._broker_truth_available():
            return {
                "status": "refused",
                "reason": "broker_truth_unavailable",
                "dry_run": dry_run,
                "actions": [],
            }
        open_positions = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        if require_no_broker_positions and open_positions and not symbols:
            return {
                "status": "refused",
                "reason": "broker_positions_open_symbol_specific_required",
                "open_broker_symbols": [display_symbol(p.symbol) for p in open_positions],
                "dry_run": dry_run,
                "actions": [],
            }

        wanted = {normalize_symbol(s) for s in symbols or [] if s}
        actions: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for norm, trades in self._open_trades_by_symbol().items():
            if wanted and norm not in wanted:
                continue
            exposure = self.exposure.get_symbol_exposure(trades[0].symbol)
            if exposure.get("broker_position_open"):
                skipped.append({"symbol": exposure.get("display_symbol"), "reason": "broker_position_open"})
                continue
            if exposure.get("effective_exposure_state") != "broker_flat_local_stale":
                skipped.append({"symbol": exposure.get("display_symbol"), "reason": exposure.get("effective_exposure_state")})
                continue
            for trade in trades:
                actions.append(self._repair_trade(trade, dry_run=dry_run))

        result = {
            "status": "ok",
            "dry_run": dry_run,
            "affected_count": len(actions),
            "actions": actions,
            "skipped": skipped,
            "broker_truth": "available",
            "records_deleted": 0,
        }
        if not dry_run:
            self.session.add(
                ActivityLog(
                    event_type="trade_state_repair",
                    message=f"Repaired {len(actions)} stale open local trade row(s) using broker-flat truth.",
                    details=result,
                )
            )
            self.session.flush()
        return result
