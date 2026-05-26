#!/usr/bin/env python3
"""Tests: pre-submit quote refresh, preflight labels, stale quote blocks."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlmodel import Session, SQLModel, create_engine

from app.database import StrategyRegistry
from app.services.order_display import enrich_execution_row, reject_reason_plain
from app.services.pre_submit_quote_service import PreSubmitQuoteService
from app.services.push_pull_strategy_seed import ensure_crypto_push_pull_baseline
from app.services.quote_freshness_service import QuoteFreshnessService, attach_quote_age


def test_stale_quote_plain_label():
    msg = reject_reason_plain("STALE_QUOTE", status="preflight_blocked")
    assert msg and "stale" in msg.lower()
    assert "broker" not in msg.lower() or "before" in msg.lower()


def test_preflight_not_broker_rejected_display():
    row = enrich_execution_row(
        {"status": "preflight_blocked", "reject_reason": "STALE_QUOTE", "broker_order_id": None}
    )
    assert row.get("blocked_before_broker") is True
    assert "Broker rejected" not in (row.get("status_label") or "")


def test_attach_quote_age_fresh():
    cfg = {"execution": {"quote_max_age_seconds": 30}}
    now = datetime.now(timezone.utc).isoformat()
    q = attach_quote_age({"bid": 1.0, "ask": 1.01, "mid": 1.005, "quote_timestamp": now}, cfg)
    assert q.get("executable") is True


def test_pre_submit_refresh_stale_then_fresh():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        ensure_crypto_push_pull_baseline(session)
        stale_ts = "2020-01-01T00:00:00Z"
        fresh_ts = datetime.now(timezone.utc).isoformat()

        with patch.object(QuoteFreshnessService, "check") as mock_check:
            mock_check.side_effect = [
                {"fresh": False, "quote": {"quote_timestamp": stale_ts}, "quote_age_seconds": 999},
                {"fresh": True, "quote": {"bid": 1, "ask": 1.01, "mid": 1.005, "quote_timestamp": fresh_ts}, "quote_age_seconds": 1},
            ]
            with patch.object(QuoteFreshnessService, "fetch_fresh") as mock_fetch:
                mock_fetch.return_value = {
                    "fresh": True,
                    "quote": {"bid": 1, "ask": 1.01, "mid": 1.005, "quote_timestamp": fresh_ts},
                    "quote_age_seconds": 1,
                    "quote_refresh_result": "fresh",
                }
                svc = PreSubmitQuoteService(session)
                out = svc.refresh_for_submit("BTC/USD", initial_quote={"quote_timestamp": stale_ts})
                assert out.get("status") == "ok"
                assert out.get("quote_refreshed") is True


def main() -> int:
    failures = []
    for name, fn in [
        ("stale_quote_plain", test_stale_quote_plain_label),
        ("preflight_display", test_preflight_not_broker_rejected_display),
        ("attach_quote_age", test_attach_quote_age_fresh),
        ("pre_submit_refresh", test_pre_submit_refresh_stale_then_fresh),
    ]:
        try:
            fn()
            print(f"OK {name}")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAIL {name}: {exc}")
    if failures:
        return 1
    print("OK verify_stale_quote_submit_suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
