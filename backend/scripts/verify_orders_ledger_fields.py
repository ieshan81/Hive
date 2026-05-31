"""/api/orders/ledger returns qty/type/price/timestamps for filled rows; missing explicit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import OrderRecord
from app.services.order_ledger_service import build_order_ledger


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_filled_row_has_fields() -> None:
    s = _mem()
    s.add(OrderRecord(symbol="SOL/USD", side="buy", qty=2.0, order_type="marketable_limit_ioc", status="filled",
                      filled_avg_price=100.0, alpaca_order_id="o1",
                      raw_payload={"filled_qty": 2.0, "limit_price": 100.5, "time_in_force": "ioc"}))
    s.commit()
    r = next(x for x in build_order_ledger(s)["orders"] if x["normalized_symbol"] == "SOLUSD")
    assert r["display_qty"] == 2.0 and r["display_price"] == 100.0, r
    assert r["order_type_label"] == "IOC marketable limit", r
    assert r["asset_class"] == "crypto" and r["display_symbol"] == "SOL/USD", r
    assert r["submitted_at"] and r["missing_fields"] == [], r
    s.close()
    print("orders-ledger: filled row -> qty/type/price/timestamps present, no missing — PASS")


def test_sparse_row_lists_missing() -> None:
    s = _mem()
    s.add(OrderRecord(symbol="AAPL", side="buy", qty=1.0, order_type="", status="rejected",
                      raw_payload={"reject_reason": "min_notional"}))
    s.commit()
    r = build_order_ledger(s)["orders"][0]
    assert "price" in r["missing_fields"] and "order_type" in r["missing_fields"], r
    assert r["reject_reason"] == "min_notional" and r["asset_class"] == "stock", r
    s.close()
    print("orders-ledger: sparse row -> missing_fields explicit (price, order_type) — PASS")


if __name__ == "__main__":
    test_filled_row_has_fields()
    test_sparse_row_lists_missing()
    print("ALL PASS: verify_orders_ledger_fields")
