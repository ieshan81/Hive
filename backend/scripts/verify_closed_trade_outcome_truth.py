"""A closed paper trade has ONE canonical, complete, consistent outcome record.

For the latest closed BTC/USD trade: broker flat, entry buy + exit sell orders exist, realized
P/L is non-null and AGREES across the trade ledger and paper_experiment_outcomes, the exit reason
is consistent across exports, a lesson is linked, and there are NO duplicate outcome rows.
Backfill is read/write DB cleanup only — it never creates an order.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

import app.database  # noqa: F401
from app.database import ExecutionLog, OrderRecord, PaperExperimentOutcome, PositionSnapshot
from app.services.closed_trade_outcome_service import ClosedTradeOutcomeService
from app.services.order_ledger_service import build_trade_ledger


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng, expire_on_commit=False)


def main() -> None:
    s = _mem()
    now = datetime.utcnow()
    # Closed BTC trade: buy filled then sell filled; broker FLAT (no open PositionSnapshot).
    s.add(OrderRecord(alpaca_order_id="BUY1", broker_client_order_id="EXPLORATION-BTCUSD-1",
                      symbol="BTC/USD", side="buy", qty=0.000170, status="filled",
                      filled_avg_price=70850.0, filled_at=now - timedelta(minutes=18), submitted_at=now - timedelta(minutes=18)))
    s.add(OrderRecord(alpaca_order_id="SELL1", broker_client_order_id="EXPLORATION-BTCUSD-1-exit",
                      symbol="BTC/USD", side="sell", qty=0.000168921, status="filled",
                      filled_avg_price=70440.0, filled_at=now, submitted_at=now))
    # Execution evidence disagrees with the training outcome (the bug we reconcile).
    s.add(ExecutionLog(event_id="x1", cycle_run_id="exploration_t1", symbol="BTC/USD", side="sell",
                       status="paper_order_filled", gates_passed_json={"exit_reason": "max_hold_exit"}))
    # Incomplete training outcome row (null pnl/prices/qty, different raw exit label).
    s.add(PaperExperimentOutcome(strategy_id="crypto_push_pull_momentum", symbol="BTC/USD",
                                 exit_reason="dynamic_stop_loss_hit", hold_minutes=18, lesson_created=True))
    s.commit()

    # Broker flat + positions_count 0.
    positions_count = int(s.exec(select(func.count()).select_from(PositionSnapshot).where(PositionSnapshot.qty > 0)).one() or 0)
    assert positions_count == 0, positions_count

    # Entry buy + exit sell orders exist.
    assert s.exec(select(OrderRecord).where(OrderRecord.side == "buy", OrderRecord.symbol == "BTC/USD")).first()
    assert s.exec(select(OrderRecord).where(OrderRecord.side == "sell", OrderRecord.symbol == "BTC/USD")).first()

    # Trade ledger (trades_history) realized P/L is non-null.
    ledger = build_trade_ledger(s)
    closed = [t for t in ledger["trades"] if t["status"] == "closed" and t["symbol"] == "BTC/USD"]
    assert closed, "expected a closed BTC trade in the ledger"
    ledger_pnl = closed[0]["gross_pnl"]
    assert ledger_pnl is not None, "trades_history realized_pl must not be null"

    # Backfill -> one canonical outcome (adopts the incomplete row, no new order).
    out = ClosedTradeOutcomeService(s).backfill()
    s.commit()
    assert out["orders_created"] == 0, out
    assert out["closed_trades_seen"] >= 1, out

    rows = list(s.exec(select(PaperExperimentOutcome).where(PaperExperimentOutcome.symbol == "BTC/USD")).all())
    assert len(rows) == 1, f"no duplicate outcomes: expected 1, got {len(rows)}"
    r = rows[0]

    # paper_experiment_outcome realized_pnl non-null and AGREES with trades_history.
    assert r.realized_pnl is not None, "paper_experiment_outcome realized_pnl must not be null"
    assert abs(float(r.realized_pnl) - float(ledger_pnl)) < 1e-6, (r.realized_pnl, ledger_pnl)

    # Every canonical field is populated (not faked — derived from orders).
    for field in ("trade_id", "entry_order_id", "exit_order_id", "entry_broker_order_id",
                  "exit_broker_order_id", "entry_client_order_id", "exit_client_order_id",
                  "entry_price", "exit_price", "qty_bought", "qty_sold", "fee_adjusted_qty_delta",
                  "realized_pnl", "realized_pnl_pct", "canonical_exit_reason", "raw_exit_trigger"):
        assert getattr(r, field) is not None, f"canonical field {field} is null"
    assert r.entry_client_order_id.startswith("EXPLORATION"), r.entry_client_order_id
    # Crypto fee deducted from sold qty -> recorded explicitly, not hidden.
    assert r.fee_adjusted_qty_delta > 0, r.fee_adjusted_qty_delta
    assert abs(r.fee_adjusted_qty_delta - (r.qty_bought - r.qty_sold)) < 1e-12, r.fee_adjusted_qty_delta

    # Exit reason is consistent across exports: canonical == legacy exit_reason, raw triggers kept.
    assert r.canonical_exit_reason == r.exit_reason, (r.canonical_exit_reason, r.exit_reason)
    raw = r.raw_exit_trigger or {}
    assert raw.get("training_outcome_exit_reason") == "dynamic_stop_loss_hit", raw
    assert raw.get("execution_evidence_exit_reason") == "max_hold_exit", raw  # preserved, not lost

    # Linked lesson exists.
    assert r.lesson_created is True, r.lesson_created

    # Idempotent: re-running backfill does not duplicate.
    ClosedTradeOutcomeService(s).backfill()
    s.commit()
    again = int(s.exec(select(func.count()).select_from(PaperExperimentOutcome).where(PaperExperimentOutcome.symbol == "BTC/USD")).one() or 0)
    assert again == 1, f"re-backfill duplicated outcomes: {again}"
    s.close()
    print(f"verify_closed_trade_outcome_truth: PASS (realized_pnl={r.realized_pnl} agrees; "
          f"canonical_exit={r.canonical_exit_reason}; fee_delta={r.fee_adjusted_qty_delta}; 1 row, no dup)")


if __name__ == "__main__":
    main()
