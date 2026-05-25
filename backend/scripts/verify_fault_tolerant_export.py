"""Fault-tolerant export and API degradation tests."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_detached_cache_fix():
    from sqlmodel import Session

    from app.database import AccountSnapshot, engine, init_db
    from app.services.alpaca_adapter import AlpacaAdapter, _SYNC_CACHE

    init_db()
    _SYNC_CACHE.clear()
    with Session(engine) as s1:
        s1.add(AccountSnapshot(equity=100, cash=50, buying_power=50, portfolio_value=100))
        s1.commit()
    with Session(engine) as s2:
        a = AlpacaAdapter(s2)
        _SYNC_CACHE["account_cached_at"] = __import__("datetime").datetime.utcnow()
        snap = a.sync_account_cached()
        assert snap is not None
        assert snap.cash == 50.0
    print("OK detached_cache_fix")


def test_bundle_when_confidence_throws():
    from sqlmodel import Session

    from app.database import engine, init_db
    from app.services.diagnostic_export import bundle_as_zip_bytes_safe

    init_db()
    with Session(engine) as session:
        with patch(
            "app.services.safe_responses.safe_confidence_summary",
            side_effect=RuntimeError("simulated confidence fail"),
        ):
            data = bundle_as_zip_bytes_safe(session)
    assert len(data) > 100
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    assert "diagnostic_export_errors.json" in names or "bundle_meta.json" in names
    print("OK bundle_partial_on_fail")


def test_safe_confidence_degraded():
    from sqlmodel import Session

    from app.database import engine, init_db
    from app.services.safe_responses import safe_confidence_summary

    init_db()
    with Session(engine) as session:
        with patch(
            "app.services.confidence_engine.ConfidenceEngine.summary",
            side_effect=ValueError("boom"),
        ):
            out = safe_confidence_summary(session)
    assert out["status"] == "degraded"
    assert out["can_unlock_live"] is False
    print("OK safe_confidence_degraded")


def test_safe_eligibility_no_tradeable_on_unknown():
    from sqlmodel import Session

    from app.database import engine, init_db
    from app.services.safe_responses import safe_account_pair_eligibility

    init_db()
    with Session(engine) as session:
        with patch(
            "app.services.safe_responses._broker_read_meta",
            return_value={
                "broker_status": "unavailable",
                "broker_sync_rate_limited": False,
                "data_freshness": "unknown",
            },
        ):
            out = safe_account_pair_eligibility(session)
    assert out["status"] == "degraded"
    assert out["eligible_count"] == 0
    print("OK eligibility_degraded")


def main():
    test_detached_cache_fix()
    test_safe_confidence_degraded()
    test_safe_eligibility_no_tradeable_on_unknown()
    test_bundle_when_confidence_throws()
    print("ALL_FAULT_TOLERANT_TESTS_PASSED")


if __name__ == "__main__":
    main()
