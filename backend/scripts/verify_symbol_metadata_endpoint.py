"""/api/symbols/metadata returns fast dynamic metadata; no crash when provider unavailable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.services.symbol_metadata_service import metadata_for, metadata_many


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_crypto_and_stock() -> None:
    s = _mem()
    res = metadata_many(s, ["BTC/USD", "AAPL", "BTCUSD"])  # BTC/USD + BTCUSD dedup to one
    assert res["count"] == 2, res
    btc = next(x for x in res["symbols"] if x["normalized_symbol"] == "BTCUSD")
    aapl = next(x for x in res["symbols"] if x["normalized_symbol"] == "AAPL")
    assert btc["asset_class"] == "crypto" and btc["session_type"] == "24/7", btc
    assert btc["display_symbol"] == "BTC/USD", btc
    assert aapl["asset_class"] == "stock" and aapl["session_type"] == "us_market_hours", aapl
    s.close()
    print("symbol-metadata: crypto + stock classified; session_type fallback works — PASS")


def test_full_name_null_no_crash() -> None:
    s = _mem()
    m = metadata_for(s, "ETH/USD")
    assert m["full_name"] is None and "full_name" in m["missing_fields"], m
    assert m["asset_class"] == "crypto" and m["session_type"] == "24/7", m
    s.close()
    print("symbol-metadata: full_name null but asset_class/session present, no crash — PASS")


def test_garbage_symbol_no_crash() -> None:
    s = _mem()
    m = metadata_for(s, "ZZZZZZ")  # provider default classifies plain alpha as equity/stock
    assert m["asset_class"] in ("unknown", "stock", "crypto"), m
    assert isinstance(m["missing_fields"], list), m
    # batch with an empty/garbage entry must not crash the endpoint
    res = metadata_many(s, ["", "123", "BTC/USD"])
    assert res["status"] == "ok" and res["count"] >= 1, res
    s.close()
    print("symbol-metadata: garbage/empty symbols handled gracefully (no crash) — PASS")


if __name__ == "__main__":
    test_crypto_and_stock()
    test_full_name_null_no_crash()
    test_garbage_symbol_no_crash()
    print("ALL PASS: verify_symbol_metadata_endpoint")
