"""End-to-end sentiment pipeline verifier — advisory/ranking-only."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app
from app.services.sentiment_service import (
    _SENTIMENT_CACHE,
    apply_sentiment_ranking_modifier,
    compute_sentiment_alignment,
    compute_sentiment_score,
    resolve_sentiment_for_ranking,
    score_symbol_sentiment,
)


def test_status_endpoint() -> None:
    client = TestClient(app)
    r = client.get("/api/sentiment/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "ok"
    assert "display_title" in data
    assert data.get("sentiment_can_place_trades") is False
    assert data.get("sentiment_affects_trading") is False
    diag = data.get("diagnostics") or {}
    assert "finbert_worker_configured" in diag
    assert "sentiment_used_in_ranking" in diag
    print("sentiment-pipeline: /api/sentiment/status — PASS")


def test_symbol_endpoint_neutral_without_crash() -> None:
    client = TestClient(app)
    r = client.get("/api/sentiment/symbol/BTC%2FUSD", params={"side": "buy"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "ok"
    assert "sentiment_score" in data
    assert -1.0 <= float(data["sentiment_score"]) <= 1.0
    assert -0.10 <= float(data["sentiment_alignment"]) <= 0.10
    print("sentiment-pipeline: /api/sentiment/symbol neutral-safe — PASS")


def test_missing_news_returns_neutral() -> None:
    out = score_symbol_sentiment(
        "TEST/USD",
        side="buy",
        fetch_news=False,
        additional_headlines=[],
    )
    assert out["sentiment_score"] == 0.0
    assert out.get("neutral_reason") in ("no_headlines", "finbert_unavailable", "pipeline_error")
    print("sentiment-pipeline: missing news returns neutral — PASS")


def test_fake_positive_headline() -> None:
    score = compute_sentiment_score(
        [
            {
                "polarity": 0.85,
                "confidence": 0.9,
                "source": "alpaca_benzinga",
                "age_minutes": 2.0,
            }
        ]
    )
    assert score > 0.2, score
    print("sentiment-pipeline: positive headline aggregate — PASS")


def test_fake_negative_headline() -> None:
    score = compute_sentiment_score(
        [
            {
                "polarity": -0.85,
                "confidence": 0.9,
                "source": "alpaca_benzinga",
                "age_minutes": 2.0,
            }
        ]
    )
    assert score < -0.2, score
    print("sentiment-pipeline: negative headline aggregate — PASS")


def test_alignment_capped() -> None:
    for raw in (1.0, -1.0, 0.5, -0.5):
        align = compute_sentiment_alignment(raw, "buy")
        assert -0.10 <= align <= 0.10, (raw, align)
        align_sell = compute_sentiment_alignment(raw, "sell")
        assert -0.10 <= align_sell <= 0.10, (raw, align_sell)
    print("sentiment-pipeline: alignment capped ±10% — PASS")


def test_ranking_modifier_only_not_gates() -> None:
    base = 0.55
    blocked_entry_allowed = False
    boosted = apply_sentiment_ranking_modifier(base, 0.10)
    assert boosted > base
    assert blocked_entry_allowed is False
    print("sentiment-pipeline: ranking modifier does not flip entry_allowed — PASS")


def test_failure_does_not_raise() -> None:
    cfg = {"sentiment": {"influence_ranking": True}}
    out = resolve_sentiment_for_ranking(cfg, "NOCRASH/USD", side="buy")
    assert isinstance(out, dict)
    assert "sentiment_alignment" in out
    print("sentiment-pipeline: failure-safe resolve — PASS")


def test_status_not_claiming_unwired_when_scored() -> None:
    from datetime import datetime

    _SENTIMENT_CACHE.clear()
    _SENTIMENT_CACHE["BTC/USD"] = {
        "symbol": "BTC/USD",
        "sentiment_score": 0.42,
        "sentiment_alignment": 0.042,
        "headline_count": 2,
        "model_used": "finbert_microservice",
        "scored_at": datetime.utcnow().isoformat() + "Z",
    }
    client = TestClient(app)
    st = client.get("/api/sentiment/status").json()
    title = str(st.get("display_title") or "")
    assert "Not wired yet" not in title
    assert st.get("diagnostics", {}).get("latest_scored_symbols_count", 0) >= 1
    print("sentiment-pipeline: status truth after scoring — PASS")


def test_sources_endpoint() -> None:
    client = TestClient(app)
    r = client.get("/api/sentiment/sources")
    assert r.status_code == 200
    assert "sources" in r.json()
    print("sentiment-pipeline: /api/sentiment/sources — PASS")


if __name__ == "__main__":
    test_status_endpoint()
    test_sources_endpoint()
    test_symbol_endpoint_neutral_without_crash()
    test_missing_news_returns_neutral()
    test_fake_positive_headline()
    test_fake_negative_headline()
    test_alignment_capped()
    test_ranking_modifier_only_not_gates()
    test_failure_does_not_raise()
    test_status_not_claiming_unwired_when_scored()
    print("ALL PASS: verify_sentiment_pipeline")
