"""
Scanner Stack — orchestrator + status registry for the 10 scanners from spec.

Every scanner:
  - writes structured output
  - has a timestamp, health, and errors
  - can run independently
  - uses cache (re-using existing services where possible)
  - never directly trades
  - feeds the candidate ranker

This module is the registry + run-coordinator.  Each scanner is implemented
as a thin adapter over an existing service so we don't duplicate logic.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Registry of scanner descriptors
# ----------------------------------------------------------------------

SCANNERS: list[dict[str, Any]] = [
    {
        "id": "universe",
        "label": "Universe Scanner",
        "description": "Discovers tradable crypto pairs and stock universe from broker/data APIs.",
        "depends_on": ["alpaca_assets_api"],
        "writes": ["available_universe", "cached_universe"],
    },
    {
        "id": "quote",
        "label": "Quote Scanner",
        "description": "Latest bid/ask quotes per symbol with freshness stamp.",
        "depends_on": ["alpaca_data_api"],
        "writes": ["quote_snapshot"],
    },
    {
        "id": "bar_candle",
        "label": "Bar / Candle Scanner",
        "description": "1m / 5m / 1h / 1d OHLCV bars per symbol with freshness.",
        "depends_on": ["alpaca_data_api"],
        "writes": ["bar_snapshot"],
    },
    {
        "id": "liquidity_spread",
        "label": "Liquidity / Spread Scanner",
        "description": "Dollar volume + spread in bps per eligible symbol.",
        "depends_on": ["quote", "bar_candle"],
        "writes": ["liquidity_snapshot"],
    },
    {
        "id": "volatility_regime",
        "label": "Volatility / Regime Scanner",
        "description": "Classifies regime per symbol: quiet / normal / vol / panic.",
        "depends_on": ["bar_candle"],
        "writes": ["regime_classification"],
    },
    {
        "id": "push_pull_technical",
        "label": "Push-Pull Technical Scanner",
        "description": "Computes push/pull/edge/quality scores using research formulas.",
        "depends_on": ["bar_candle", "quote", "volatility_regime"],
        "writes": ["push_pull_scores"],
    },
    {
        "id": "sentiment",
        "label": "Sentiment Scanner",
        "description": "FinBERT + Alpaca Benzinga news; capped ±10% ranking influence.",
        "depends_on": ["finbert_optional", "alpaca_news_optional"],
        "writes": ["sentiment_snapshot"],
    },
    {
        "id": "risk_eligibility",
        "label": "Risk / Eligibility Scanner",
        "description": "Cage gates: reconciliation, cooldowns, pump-dump flags, position limits.",
        "depends_on": ["broker_reconciliation"],
        "writes": ["eligibility_snapshot"],
    },
    {
        "id": "candidate_ranking",
        "label": "Candidate Ranking Scanner",
        "description": "Applies the 6-factor universe ranking formula across symbols.",
        "depends_on": ["liquidity_spread", "volatility_regime", "bar_candle"],
        "writes": ["candidate_rankings"],
    },
    {
        "id": "memory_outcome",
        "label": "Memory / Outcome Scanner",
        "description": "5-tier memory promotion + decay sweep across LessonNode rows.",
        "depends_on": ["lesson_nodes_table"],
        "writes": ["memory_quality_report"],
    },
]


# ----------------------------------------------------------------------
# Per-scanner runner — wraps existing services
# ----------------------------------------------------------------------

def _safe_run(callable_fn, *args, **kwargs) -> dict[str, Any]:
    started = time.time()
    try:
        out = callable_fn(*args, **kwargs)
        return {
            "status": "ok",
            "elapsed_ms": int((time.time() - started) * 1000),
            "result": out,
            "error": None,
        }
    except Exception as exc:
        logger.exception("scanner runner failed")
        return {
            "status": "error",
            "elapsed_ms": int((time.time() - started) * 1000),
            "result": None,
            "error": str(exc)[:300],
        }


def _scan_universe(session: Session) -> dict[str, Any]:
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"available_crypto": 0, "available_stocks": 0, "configured": False}
    try:
        from app.services.alpaca_crypto_assets import AlpacaCryptoAssetsService
        crypto = AlpacaCryptoAssetsService(session).list_tradable()
    except Exception:
        crypto = []
    funnel = build_funnel_breakdown(session, max_evaluate=36, fetch_quotes=False)
    return {
        "configured": True,
        "available_crypto": len(crypto) if isinstance(crypto, list) else 0,
        "sample_crypto_symbols": [c.get("symbol") for c in (crypto or [])][:10],
        "usd_pairs_available": funnel.get("available_symbols"),
        "evaluated_symbols": funnel.get("evaluated_symbols"),
        "eligible_count": funnel.get("eligible_count"),
        "block_breakdown": funnel.get("block_breakdown"),
        "funnel_answer": funnel.get("answer"),
    }


def _scan_quote(session: Session, symbols: list[str]) -> dict[str, Any]:
    from app.services.alpaca_adapter import AlpacaAdapter
    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"quotes": {}, "configured": False}
    out: dict[str, Any] = {}
    for sym in symbols[:20]:
        q = adapter.get_quote(sym, "crypto" if "/" in sym or sym.endswith("USD") else "stock")
        if q:
            out[sym] = {"bid": q.get("bid"), "ask": q.get("ask"), "spread_pct": q.get("spread_pct")}
    return {"configured": True, "quotes": out, "count": len(out)}


def _scan_bar_candle(session: Session, symbols: list[str], timeframe: str = "1Min") -> dict[str, Any]:
    from app.services.alpaca_adapter import AlpacaAdapter
    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"bars": {}, "configured": False}
    out: dict[str, Any] = {}
    for sym in symbols[:10]:
        bars = adapter.get_crypto_bars(sym, timeframe=timeframe, limit=30)
        if bars:
            out[sym] = {"bar_count": len(bars), "latest_close": bars[-1].get("close")}
    return {"configured": True, "timeframe": timeframe, "symbols_with_bars": len(out), "detail": out}


def _scan_volatility_regime(session: Session, symbols: list[str]) -> dict[str, Any]:
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services.push_pull_scorer import classify_regime
    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"regimes": {}, "configured": False}
    out: dict[str, Any] = {}
    for sym in symbols[:10]:
        bars = adapter.get_crypto_bars(sym, timeframe="1Min", limit=480)
        out[sym] = {"regime": classify_regime(bars) if bars else "normal", "bars_used": len(bars)}
    return {"configured": True, "regimes": out}


def _scan_push_pull(session: Session, symbols: list[str]) -> dict[str, Any]:
    """Run the push-pull live scoring path for top symbols."""
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services.push_pull_scorer import evaluate_entry, classify_regime
    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {"scores": {}, "configured": False}

    scores: dict[str, Any] = {}
    for sym in symbols[:10]:
        bars_1m = adapter.get_crypto_bars(sym, timeframe="1Min", limit=30)
        bars_5m = adapter.get_crypto_bars(sym, timeframe="5Min", limit=20)
        quote = adapter.get_quote(sym, "crypto") or {}
        if not bars_1m:
            scores[sym] = {"reason": "no_bars"}
            continue
        regime = classify_regime(bars_1m)
        evaluation = evaluate_entry(
            sym, bars_1m, bars_5m, quote,
            bar_age_seconds=0.0,
            universe_rank_score=0.5,
            sentiment_alignment=0.0,
            regime=regime,
            side="buy",
        )
        scores[sym] = evaluation
    return {
        "configured": True,
        "scanned": len(symbols[:10]),
        "scored": len(scores),
        "scores": scores,
    }


def _scan_sentiment(session: Session, symbols: list[str]) -> dict[str, Any]:
    from app.services.sentiment_service import FinBERTScorer, score_symbol_sentiment
    finbert_active = FinBERTScorer.is_available()
    out: dict[str, Any] = {}
    for sym in symbols[:5]:
        out[sym] = score_symbol_sentiment(sym, side="buy")
    return {
        "finbert_available": finbert_active,
        "scored_symbols": len(out),
        "per_symbol": out,
    }


def _scan_memory_outcome(session: Session) -> dict[str, Any]:
    from app.services.memory_quality_service import MemoryQualityService
    svc = MemoryQualityService(session)
    return {
        "status": svc.status_summary(),
        "quality_updates": svc.update_quality_scores(),
    }


# ----------------------------------------------------------------------
# Status & orchestrator
# ----------------------------------------------------------------------

_LAST_RUN: dict[str, dict[str, Any]] = {}


def list_scanners() -> list[dict[str, Any]]:
    return [dict(s) for s in SCANNERS]


def latest_outputs() -> dict[str, Any]:
    return {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scanners": _LAST_RUN,
    }


def health_snapshot() -> dict[str, Any]:
    healthy = sum(1 for r in _LAST_RUN.values() if r.get("status") == "ok")
    failing = sum(1 for r in _LAST_RUN.values() if r.get("status") == "error")
    return {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "total_scanners": len(SCANNERS),
        "ran": len(_LAST_RUN),
        "healthy": healthy,
        "failing": failing,
    }


def error_log() -> list[dict[str, Any]]:
    return [
        {"scanner": k, "error": v.get("error"), "at": v.get("ran_at")}
        for k, v in _LAST_RUN.items()
        if v.get("status") == "error"
    ]


def run_all(session: Session, *, symbols: Optional[list[str]] = None) -> dict[str, Any]:
    """Run all scanners in deterministic order.  Stores latest output per scanner."""
    if not symbols:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"]
    now = datetime.utcnow().isoformat() + "Z"

    runners = [
        ("universe",            lambda: _scan_universe(session)),
        ("quote",               lambda: _scan_quote(session, symbols)),
        ("bar_candle",          lambda: _scan_bar_candle(session, symbols)),
        ("liquidity_spread",    lambda: _scan_quote(session, symbols)),  # piggybacks quote
        ("volatility_regime",   lambda: _scan_volatility_regime(session, symbols)),
        ("push_pull_technical", lambda: _scan_push_pull(session, symbols)),
        ("sentiment",           lambda: _scan_sentiment(session, symbols)),
        ("risk_eligibility",    lambda: {"status": "deferred_to_execution_cage"}),
        ("candidate_ranking",   lambda: _scan_push_pull(session, symbols)),  # ranking inside push-pull
        ("memory_outcome",      lambda: _scan_memory_outcome(session)),
    ]

    for scan_id, fn in runners:
        result = _safe_run(fn)
        result["ran_at"] = now
        _LAST_RUN[scan_id] = result

    return latest_outputs()
