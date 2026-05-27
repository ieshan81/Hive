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

@router.get("/radar")
def radar(session: Session = Depends(get_session)):
    """Hybrid radar snapshot — full funnel, tiers, ranked, shortlist."""
    from app.services.hybrid_radar_service import hybrid_radar_snapshot

    return hybrid_radar_snapshot(session)


@router.get("/tiers")
def tiers(session: Session = Depends(get_session)):
    from app.services.hybrid_radar_service import universe_tiers

    return universe_tiers(session)


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
    """Universe radar funnel with exact block-reason breakdown."""
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    return build_funnel_breakdown(session, max_evaluate=36, fetch_quotes=True)


@router.get("/execution-shortlist")
def execution_shortlist(session: Session = Depends(get_session)):
    """Top-N symbols that survived the full funnel."""
    payload = rankings(session)
    pipe = (payload or {}).get("pipeline") or {}
    return {
        "status": "ok",
        "generated_at_utc": payload.get("generated_at_utc"),
        "answer": payload.get("answer"),
        "block_breakdown": payload.get("block_breakdown"),
        "shortlist": pipe.get("shortlist", []),
        "execution_shortlist_count": pipe.get("funnel", {}).get("execution_shortlist", 0),
        "eligible_count": payload.get("eligible_count", 0),
        "why_zero_eligible": payload.get("answer") if payload.get("eligible_count") == 0 else None,
    }


@router.post("/refresh")
def refresh(session: Session = Depends(get_session)):
    """Force a universe pipeline rebuild + symbol identity cache refresh."""
    from app.services import symbol_identity_service

    symbol_identity_service.refresh_cache()
    return rankings(session)
