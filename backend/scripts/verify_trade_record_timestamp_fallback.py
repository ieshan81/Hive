"""TradeRecord has no created_at — confidence/cockpit/export must not crash on it.

Root cause: TradeRecord uses opened_at/closed_at (no created_at column at all), so any
direct `trade.created_at` raises AttributeError and 500s the confidence endpoints. The
shared safe_record_timestamp helper falls back created_at -> opened_at -> ... so the
endpoints stay up and still get a correct timestamp.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import TradeRecord
from app.services.timestamp_safety import safe_record_timestamp


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_traderecord_has_no_created_at_but_no_crash() -> None:
    t = TradeRecord(symbol="SOL/USD", side="buy", entry_price=100.0, quantity=1.0, status="closed")
    assert not hasattr(t, "created_at"), "TradeRecord unexpectedly has created_at"
    ts = safe_record_timestamp(t)
    assert ts == t.opened_at and ts is not None, ts  # falls back to opened_at
    print("timestamp: TradeRecord (no created_at) -> opened_at, no AttributeError — PASS")


def test_empty_object_returns_none() -> None:
    class Bare:
        pass

    assert safe_record_timestamp(Bare()) is None
    assert safe_record_timestamp({"foo": 1}) is None
    print("timestamp: object with no timestamp fields -> None (no crash) — PASS")


def test_confidence_engine_no_crash_on_traderecord() -> None:
    """ConfidenceEngine.by_strategy/by_symbol previously did t.created_at and 500'd once a
    reset epoch was set. With the fix they run clean even with trades present."""
    from app.services.confidence_engine import ConfidenceEngine

    session = _mem()
    session.add(TradeRecord(symbol="SOL/USD", strategy="crypto_push_pull", side="buy", entry_price=100.0, quantity=1.0, status="closed", pl_dollars=1.5))
    session.add(TradeRecord(symbol="LTC/USD", strategy="crypto_push_pull", side="buy", entry_price=50.0, quantity=2.0, status="closed", pl_dollars=-0.8))
    session.commit()

    eng = ConfidenceEngine(session)
    # Force the post-nuke filter path that touched .created_at (the crash path).
    eng._reset_epoch = {"nuke_completed_at": "2020-01-01T00:00:00"}
    bs = eng.by_strategy()
    bsym = eng.by_symbol()
    assert isinstance(bs, dict) and isinstance(bsym, dict), (type(bs), type(bsym))
    session.close()
    print("confidence: by_strategy/by_symbol run without TradeRecord.created_at crash — PASS")


if __name__ == "__main__":
    test_traderecord_has_no_created_at_but_no_crash()
    test_empty_object_returns_none()
    test_confidence_engine_no_crash_on_traderecord()
    print("ALL PASS: verify_trade_record_timestamp_fallback")
