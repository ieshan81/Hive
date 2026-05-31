"""FIFO trade pairing: BTC/USD buy pairs with BTCUSD sell; partials + dust handled."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import OrderRecord
from app.services.order_ledger_service import build_trade_ledger

T0 = datetime(2026, 5, 30, 10, 0, 0)


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _order(s, symbol, side, qty, price, mins, oid):
    s.add(OrderRecord(symbol=symbol, side=side, qty=qty, status="filled", filled_avg_price=price,
                      alpaca_order_id=oid, submitted_at=T0 + timedelta(minutes=mins),
                      filled_at=T0 + timedelta(minutes=mins), raw_payload={"filled_qty": qty}))


def test_cross_format_pairing() -> None:
    s = _mem()
    _order(s, "BTC/USD", "buy", 1.0, 100.0, 0, "b1")
    _order(s, "BTCUSD", "sell", 1.0, 110.0, 30, "s1")  # different format, same asset
    s.commit()
    trades = build_trade_ledger(s)["trades"]
    closed = [t for t in trades if t["status"] == "closed"]
    assert len(closed) == 1, trades
    assert abs(closed[0]["gross_pnl"] - 10.0) < 1e-6, closed[0]
    assert closed[0]["estimated_fees"] is None and closed[0]["net_pnl"] is None, closed[0]
    assert closed[0]["pairing_confidence"] == "high" and closed[0]["hold_minutes"] == 30.0, closed[0]
    s.close()
    print("trade-pairing: BTC/USD buy + BTCUSD sell -> 1 closed, gross 10, fees null — PASS")


def test_partial_fill_and_dust() -> None:
    s = _mem()
    _order(s, "BTC/USD", "buy", 1.0, 100.0, 0, "b1")
    _order(s, "BTCUSD", "sell", 0.9999, 110.0, 30, "s1")  # leaves ~0.0001 dust; broker flat (no position)
    s.commit()
    trades = build_trade_ledger(s)["trades"]
    closed = [t for t in trades if t["status"] == "closed"]
    dust = [t for t in trades if t["status"] == "dust_residual"]
    assert len(closed) == 1 and len(dust) == 1, trades
    assert closed[0]["pairing_confidence"] == "medium", closed[0]
    s.close()
    print("trade-pairing: partial fill -> closed + dust_residual (broker flat) — PASS")


def test_summary_gross_only() -> None:
    s = _mem()
    _order(s, "BTC/USD", "buy", 1.0, 100.0, 0, "b1")
    _order(s, "BTC/USD", "sell", 1.0, 110.0, 10, "s1")
    s.commit()
    summ = build_trade_ledger(s)["summary"]
    assert summ["closed_trades"] == 1 and abs(summ["gross_pnl"] - 10.0) < 1e-6, summ
    assert summ["estimated_net_pnl"] is None and summ["fees_available"] is False, summ
    s.close()
    print("trade-pairing: summary gross P&L correct, net null (no fee data) — PASS")


if __name__ == "__main__":
    test_cross_format_pairing()
    test_partial_fill_and_dust()
    test_summary_gross_only()
    print("ALL PASS: verify_trade_pairing_ledger")
