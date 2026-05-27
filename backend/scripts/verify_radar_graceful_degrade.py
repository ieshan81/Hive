#!/usr/bin/env python3
"""Verify radar/readiness graceful degradation — never 500 on rate limits or null quotes."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


def test_null_bid_ask_metrics():
    from app.services.universe_ranking_service import extract_symbol_metrics

    from datetime import datetime, timezone

    bars = [
        {
            "close": 100.0,
            "high": 101,
            "low": 99,
            "volume": 10,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    m = extract_symbol_metrics("BTC/USD", bars, {"bid": None, "ask": None})
    assert m["ineligible_reason"] == "stale_or_missing_quote"
    assert m["eligible"] is False


def test_empty_bars_metrics():
    from app.services.universe_ranking_service import extract_symbol_metrics

    m = extract_symbol_metrics("BTC/USD", [], {})
    assert m["ineligible_reason"] == "no_bars"
    assert m["eligible"] is False


def test_missing_quote_metrics():
    from app.services.universe_ranking_service import extract_symbol_metrics

    bars = [{"close": 50.0, "high": 51, "low": 49, "volume": 5, "timestamp": "2026-05-27T08:00:00"}]
    m = extract_symbol_metrics("ETH/USD", bars, {})
    assert m["ineligible_reason"] == "stale_or_missing_quote"


def test_degraded_radar_snapshot_shape():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services.hybrid_radar_service import hybrid_radar_snapshot

    init_db()
    with Session(engine) as session:
        with patch("app.services.hybrid_radar_service.build_funnel_breakdown", side_effect=RuntimeError("boom")):
            out = hybrid_radar_snapshot(session, fetch_quotes=False)
    assert out["status"] == "degraded"
    assert out["execution_shortlist"] == []
    assert out["paper_trade_allowed"] is False
    assert "reason" in out


def test_rate_limited_funnel_degrades():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    init_db()
    with Session(engine) as session:
        mock_adapter = MagicMock()
        mock_adapter.configured = True
        mock_adapter.broker_sync_rate_limited = True
        with patch(
            "app.services.universe_strategy_discovery_service.AlpacaAdapter",
            return_value=mock_adapter,
        ):
            with patch(
                "app.services.universe_strategy_discovery_service._load_usd_universe",
                return_value=(["BTC/USD", "ETH/USD"], {"BTC/USD": {"tradable": True}}),
            ):
                with patch(
                    "app.services.universe_strategy_discovery_service.evaluate_symbol_blocks",
                    return_value={
                        "symbol": "BTC/USD",
                        "blocks": ["stale_bar"],
                        "eligible": False,
                        "metrics": {"symbol": "BTC/USD", "eligible": False},
                    },
                ):
                    funnel = build_funnel_breakdown(session, {}, max_evaluate=2, fetch_quotes=True)
    assert funnel["status"] == "degraded"
    assert funnel["reason"] == "alpaca_rate_limited"
    assert funnel["cached_data_used"] is True


def test_crypto_readiness_returns_degraded_not_raises():
    from app.database import engine, init_db
    from sqlmodel import Session
    from app.routers.market_sessions import crypto_readiness

    init_db()
    with Session(engine) as session:
        with patch(
            "app.routers.market_sessions.hybrid_radar_snapshot",
            return_value={
                "status": "degraded",
                "reason": "alpaca_rate_limited",
                "cached_data_used": True,
                "retry_after_seconds": 90,
                "stale_symbols": ["BTC/USD"],
                "unavailable_symbols": [],
                "counts": {"evaluated": 36, "eligible": 0, "execution_shortlist": 0},
                "execution_shortlist": [],
                "lesser_known_highlights": [],
                "paper_trade_allowed": False,
            },
        ):
            out = crypto_readiness(session)
    assert out["status"] == "degraded"
    assert out["reason"] == "alpaca_rate_limited"
    assert out["paper_trade_allowed"] is False
    assert out["execution_shortlist"] == 0


def main() -> None:
    test_null_bid_ask_metrics()
    test_empty_bars_metrics()
    test_missing_quote_metrics()
    test_degraded_radar_snapshot_shape()
    test_rate_limited_funnel_degrades()
    test_crypto_readiness_returns_degraded_not_raises()
    print("verify_radar_graceful_degrade: OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("verify_radar_graceful_degrade: FAIL", exc)
        sys.exit(1)
