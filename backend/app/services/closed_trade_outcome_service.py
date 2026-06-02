"""Canonical closed-trade outcome truth.

One canonical PaperExperimentOutcome per closed paper trade, reconciled from the trade ledger
(FIFO-paired buy/sell fills) + OrderRecord, so trades_history, paper_experiment_outcomes,
training_outcomes, the memory lesson, and the dashboard all agree.

READ/WRITE DB CLEANUP ONLY. Never submits an order, never enables live, never invents values —
it only backfills from OrderRecord, ExecutionLog, PositionSnapshot, broker payload, and the
trade ledger.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PaperExperimentOutcome
from app.services.order_ledger_service import build_trade_ledger


def _norm(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").strip()


# Map raw exit triggers to a small canonical vocabulary (consistent across every export).
_EXIT_REASON_CANON = {
    "max_hold_exit": "max_hold_time",
    "max_hold_time": "max_hold_time",
    "dynamic_stop_loss_hit": "stop_loss",
    "stop_loss": "stop_loss",
    "stop_loss_hit": "stop_loss",
    "take_profit_hit": "take_profit",
    "take_profit": "take_profit",
    "trailing_stop_hit": "trailing_stop",
    "session_end_exit": "session_end",
    "invalidation": "invalidation",
}


def _canon_reason(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = str(raw).strip().lower()
    return _EXIT_REASON_CANON.get(key, key)


class ClosedTradeOutcomeService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def _order_by_broker_id(self, broker_id: Optional[str]) -> Optional[OrderRecord]:
        if not broker_id:
            return None
        return self.session.exec(
            select(OrderRecord).where(OrderRecord.alpaca_order_id == str(broker_id))
        ).first()

    def _exit_execution_reason(self, symbol: str) -> Optional[str]:
        """Best-effort execution-evidence exit reason for the symbol's most recent sell log."""
        rows = self.session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.symbol == symbol, ExecutionLog.side == "sell")
            .order_by(ExecutionLog.created_at.desc())
            .limit(1)
        ).all()
        if not rows:
            return None
        log = rows[0]
        gp = log.gates_passed_json if isinstance(log.gates_passed_json, dict) else {}
        gf = log.gates_failed_json if isinstance(log.gates_failed_json, dict) else {}
        return gp.get("exit_reason") or gf.get("exit_reason") or log.reject_reason

    def build_canonical(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Return one canonical record per CLOSED trade from the ledger + OrderRecord."""
        ledger = build_trade_ledger(self.session, limit=limit)
        out: list[dict[str, Any]] = []
        for t in ledger.get("trades", []):
            if t.get("status") != "closed":
                continue
            buy = self._order_by_broker_id(t.get("entry_order_id"))
            sell = self._order_by_broker_id(t.get("exit_order_id"))
            symbol = t.get("symbol") or (buy.symbol if buy else None) or (sell.symbol if sell else None)
            qty_bought = float(buy.qty) if buy and buy.qty is not None else None
            qty_sold = float(sell.qty) if sell and sell.qty is not None else (t.get("qty"))
            delta = None
            if qty_bought is not None and qty_sold is not None:
                delta = round(qty_bought - qty_sold, 12)
            entry_price = t.get("entry_price")
            realized_pnl = t.get("gross_pnl")
            realized_pnl_pct = t.get("pnl_pct")

            # Reconcile the exit reason: gather every source, pick a deterministic canonical,
            # preserve all raw triggers so nothing is hidden.
            ledger_reason = t.get("exit_reason")
            exec_reason = self._exit_execution_reason(symbol) if symbol else None
            existing = self._find_existing(symbol, t.get("strategy"))
            existing_reason = existing.exit_reason if existing else None
            raw_triggers = {
                "ledger_exit_reason": ledger_reason,
                "execution_evidence_exit_reason": exec_reason,
                "training_outcome_exit_reason": existing_reason,
            }
            canonical = _canon_reason(
                exec_reason or existing_reason or ledger_reason
            ) or "position_closed"

            strategy_id = t.get("strategy") or (existing.strategy_id if existing else None) or "unknown"
            trade_id = f"{_norm(symbol or '')}|{t.get('entry_order_id')}|{t.get('exit_order_id')}"
            out.append({
                "trade_id": trade_id,
                "symbol": symbol,
                "strategy_id": strategy_id,
                "entry_order_id": buy.id if buy else None,
                "exit_order_id": sell.id if sell else None,
                "entry_broker_order_id": t.get("entry_order_id"),
                "exit_broker_order_id": t.get("exit_order_id"),
                "entry_client_order_id": buy.broker_client_order_id if buy else None,
                "exit_client_order_id": sell.broker_client_order_id if sell else None,
                "entry_price": entry_price,
                "exit_price": t.get("exit_price"),
                "qty": qty_sold,
                "qty_bought": qty_bought,
                "qty_sold": qty_sold,
                "fee_adjusted_qty_delta": delta,
                "realized_pnl": realized_pnl,
                "realized_pnl_pct": realized_pnl_pct,
                "fees_estimated": t.get("estimated_fees"),  # null unless truly known — never invented
                "hold_minutes": t.get("hold_minutes"),
                "canonical_exit_reason": canonical,
                "raw_exit_trigger": raw_triggers,
                "existing_id": existing.id if existing else None,
            })
        return out

    def _find_existing(self, symbol: Optional[str], strategy: Optional[str]) -> Optional[PaperExperimentOutcome]:
        """Find an existing (possibly incomplete) outcome row for this trade to adopt, so we
        update in place instead of creating a duplicate."""
        if not symbol:
            return None
        rows = list(
            self.session.exec(
                select(PaperExperimentOutcome)
                .where(PaperExperimentOutcome.symbol == symbol)
                .order_by(PaperExperimentOutcome.created_at.desc())
            ).all()
        )
        if strategy:
            for r in rows:
                if r.strategy_id == strategy and r.realized_pnl is None and not r.trade_id:
                    return r
        for r in rows:
            if r.realized_pnl is None and not r.trade_id:
                return r
        return None

    def backfill(self, *, limit: int = 200, operator: str = "outcome_backfill") -> dict[str, Any]:
        """Upsert ONE canonical PaperExperimentOutcome per closed trade. Idempotent; no duplicates;
        never submits orders."""
        canon = self.build_canonical(limit=limit)
        updated = created = 0
        for c in canon:
            row = self.session.exec(
                select(PaperExperimentOutcome).where(PaperExperimentOutcome.trade_id == c["trade_id"])
            ).first()
            if row is None and c.get("existing_id"):
                row = self.session.get(PaperExperimentOutcome, c["existing_id"])
            is_new = row is None
            if is_new:
                row = PaperExperimentOutcome(strategy_id=c["strategy_id"], symbol=c["symbol"])
            for field in (
                "trade_id", "strategy_id", "symbol", "entry_order_id", "exit_order_id",
                "entry_broker_order_id", "exit_broker_order_id", "entry_client_order_id",
                "exit_client_order_id", "entry_price", "exit_price", "qty", "qty_bought",
                "qty_sold", "fee_adjusted_qty_delta", "realized_pnl", "realized_pnl_pct",
                "fees_estimated", "hold_minutes", "canonical_exit_reason", "raw_exit_trigger",
            ):
                setattr(row, field, c[field])
            # Keep the legacy exit_reason aligned to the canonical value for cross-export agreement.
            row.exit_reason = c["canonical_exit_reason"]
            row.outcome_source = "canonical_backfill"
            row.lesson_created = True
            self.session.add(row)
            created += int(is_new)
            updated += int(not is_new)
        self.session.flush()
        return {
            "status": "ok",
            "closed_trades_seen": len(canon),
            "outcomes_created": created,
            "outcomes_updated": updated,
            "orders_created": 0,
        }

    def canonical_export(self, *, limit: int = 100) -> dict[str, Any]:
        """READ ONLY: canonical closed outcomes for diagnostics / dashboard agreement."""
        rows = list(
            self.session.exec(
                select(PaperExperimentOutcome)
                .where(PaperExperimentOutcome.trade_id != None)  # noqa: E711
                .order_by(PaperExperimentOutcome.created_at.desc())
                .limit(limit)
            ).all()
        )
        return {
            "status": "ok",
            "count": len(rows),
            "outcomes": [
                {
                    "trade_id": r.trade_id, "symbol": r.symbol, "strategy_id": r.strategy_id,
                    "entry_order_id": r.entry_order_id, "exit_order_id": r.exit_order_id,
                    "entry_broker_order_id": r.entry_broker_order_id, "exit_broker_order_id": r.exit_broker_order_id,
                    "entry_client_order_id": r.entry_client_order_id, "exit_client_order_id": r.exit_client_order_id,
                    "entry_price": r.entry_price, "exit_price": r.exit_price,
                    "qty_bought": r.qty_bought, "qty_sold": r.qty_sold,
                    "fee_adjusted_qty_delta": r.fee_adjusted_qty_delta,
                    "realized_pnl": r.realized_pnl, "realized_pnl_pct": r.realized_pnl_pct,
                    "fees_estimated": r.fees_estimated, "hold_minutes": r.hold_minutes,
                    "canonical_exit_reason": r.canonical_exit_reason, "raw_exit_trigger": r.raw_exit_trigger,
                    "lesson_created": r.lesson_created,
                }
                for r in rows
            ],
        }
