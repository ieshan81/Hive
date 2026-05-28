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
    from app.services.config_manager import ConfigManager

    cfg = ConfigManager(session).get_current()
    return hybrid_radar_snapshot(session, cfg, fetch_quotes=False)


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
    """Fast universe radar funnel.

    GET is page-safe: it does not live-fetch every quote. Symbols may rank from
    cached bars, but execution still requires fresh quotes in the risk cage.
    Use POST /api/universe/refresh for an operator-triggered live rebuild.
    """
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    return build_funnel_breakdown(session, max_evaluate=36, fetch_quotes=False)


@router.get("/execution-shortlist")
def execution_shortlist(session: Session = Depends(get_session)):
    """Eligible paper entries — all symbols that pass gates (no shortlist cap)."""
    return _eligible_trades_payload(session)


@router.get("/eligible-trades")
def eligible_trades(session: Session = Depends(get_session)):
    """Canonical eligible-trades list for Universe UI and agent cycles."""
    return _eligible_trades_payload(session)


def _eligible_trades_payload(session: Session) -> dict:
    from app.services.config_manager import ConfigManager
    from app.services.engine_config import cfg_get
    from app.services.trader_console_service import trader_console_status

    cfg = ConfigManager(session).get_current()
    payload = trader_console_status(session)
    eligible = payload.get("eligible_trades") or payload.get("shortlist") or []
    trade_all = bool(cfg_get(cfg, "universe.trade_all_eligible", True))
    scored = int(payload.get("scored_symbols") or 0)
    why_zero = None
    if not eligible:
        why_zero = (
            f"Scored {scored} symbols; none passed hard paper gates yet. "
            f"Blockers: {payload.get('no_trade_reason_breakdown') or {}}"
        )
    msg = payload.get("message") or (
        f"{len(eligible)} eligible — agent trades all each cycle."
        if eligible
        else "No eligible symbols this scan."
    )
    return {
        "status": payload.get("status") or "ok",
        "generated_at_utc": payload.get("generated_at_utc"),
        "answer": msg,
        "block_breakdown": payload.get("no_trade_reason_breakdown") or {},
        "eligible_trades": eligible,
        "shortlist": eligible,
        "strict_shortlist": [],
        "paper_exploration_shortlist": eligible,
        "shortlist_mode": "trade_all_eligible" if trade_all else "paper_exploration",
        "trade_all_eligible": trade_all,
        "execution_shortlist_count": len(eligible),
        "eligible_count": len(eligible),
        "paper_exploration_shortlist_count": len(eligible),
        "scored_symbols": scored,
        "selected_candidate": eligible[0] if eligible else None,
        "no_trade_reason_breakdown": payload.get("no_trade_reason_breakdown") or {},
        "why_zero_eligible": why_zero,
    }


@router.post("/refresh")
def refresh(session: Session = Depends(get_session)):
    """Force a universe pipeline rebuild + symbol identity cache refresh."""
    from app.services import symbol_identity_service
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    symbol_identity_service.refresh_cache()
    return build_funnel_breakdown(session, max_evaluate=36, fetch_quotes=True)
