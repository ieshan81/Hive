from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.universe_service import universe_status

    return universe_status(session)


@router.get("/scan-summary")
def scan_summary(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import universe_scan_summary

    return universe_scan_summary(session)


@router.get("/sources")
def sources(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import universe_sources

    return universe_sources(session)


@router.get("/assets/crypto")
def assets_crypto(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import universe_assets_crypto

    return universe_assets_crypto(session)


@router.get("/assets/stocks")
def assets_stocks(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import universe_assets_stocks

    return universe_assets_stocks(session)


@router.get("/eligibility")
def eligibility(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import universe_eligibility

    return universe_eligibility(session)


@router.get("/freshness")
def freshness(session: Session = Depends(get_session)):
    from app.services.universe_sources_service import universe_freshness

    return universe_freshness(session)


@router.get("/mode")
def mode(session: Session = Depends(get_session)):
    from app.services.universe_mode_service import universe_mode_status

    return universe_mode_status(session)


@router.get("/filters")
def filters(session: Session = Depends(get_session)):
    from app.services.universe_mode_service import universe_filters

    return universe_filters(session)


@router.get("/block-reasons")
def block_reasons(session: Session = Depends(get_session)):
    from app.services.universe_mode_service import universe_block_reasons

    return universe_block_reasons(session)


# ─────────────────────────────────────────────────────────────────────────
# Full-pipeline endpoints (Caged Hive Quant Universe Radar)
# ─────────────────────────────────────────────────────────────────────────

@router.get("/cache")
def cache(session: Session = Depends(get_session)):
    """Universe cache snapshot — counts, freshness, source metadata."""
    from app.services.universe_sources_service import universe_scan_summary
    from app.services import symbol_identity_service
    from datetime import datetime

    summary = universe_scan_summary(session)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scan_summary": summary,
        "symbol_identity_cache": symbol_identity_service.cache_snapshot(),
    }


@router.get("/rankings")
def rankings(session: Session = Depends(get_session)):
    """Apply the 6-factor universe ranking formula across live cached symbols."""
    from datetime import datetime
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services import universe_ranking_service as urs
    from app.services.alpaca_crypto_assets import fetch_crypto_assets

    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {
            "status": "ok",
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "mode": "unavailable",
            "rankings": [],
            "note": "Alpaca not configured — ranking pipeline cannot fetch data.",
        }

    # Full radar: use Alpaca crypto assets API to determine the available universe,
    # then evaluate a capped subset to avoid rate-limit explosions on run-once calls.
    assets = fetch_crypto_assets(force=False) or {}
    available = sorted([s for s in assets.keys() if s.endswith("/USD")])
    max_eval = 30
    symbols = available[:max_eval] if available else ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"]

    metrics: list[dict] = []
    for sym in symbols:
        bars = adapter.get_crypto_bars(sym, timeframe="1Min", limit=30) or []
        quote = adapter.get_quote(sym, "crypto") or {}
        metrics.append(urs.extract_symbol_metrics(sym, bars, quote))

    ranked = urs.rank_universe(metrics)
    snapshot = urs.build_pipeline_snapshot(available or symbols, metrics, ranked, max_shortlist=10)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "pipeline": snapshot,
        "available_universe_count": len(available),
        "evaluated_symbols_count": len(symbols),
        "note": (
            f"Universe radar evaluates a capped subset ({max_eval}) per call to avoid provider rate limits. "
            "Execution shortlist is derived from the ranked subset; curated watchlist is only the UI shortlist."
        ),
    }


@router.get("/execution-shortlist")
def execution_shortlist(session: Session = Depends(get_session)):
    """Top-N symbols that survived the full funnel."""
    payload = rankings(session)
    pipe = (payload or {}).get("pipeline") or {}
    return {
        "status": "ok",
        "generated_at_utc": payload.get("generated_at_utc"),
        "shortlist": pipe.get("shortlist", []),
        "execution_shortlist_count": pipe.get("funnel", {}).get("execution_shortlist", 0),
    }


@router.post("/refresh")
def refresh(session: Session = Depends(get_session)):
    """Force a universe pipeline rebuild + symbol identity cache refresh."""
    from app.services import symbol_identity_service

    symbol_identity_service.refresh_cache()
    return rankings(session)
