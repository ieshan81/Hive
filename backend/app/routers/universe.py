from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: DB/cache state only. Use POST /api/universe/refresh for provider scans.
    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    candidates = universe.get("top_candidates") or []
    crypto = [c for c in candidates if "/" in str(c.get("symbol") or "")]
    stock = [c for c in candidates if "/" not in str(c.get("symbol") or "")]
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "sources_summary": {
            "source_counts": {
                "cached_symbols": (universe.get("funnel") or {}).get("cached", 0),
                "fresh_symbols": (universe.get("funnel") or {}).get("fresh", 0),
                "eligible_symbols": (universe.get("funnel") or {}).get("eligible", 0),
                "shortlisted_symbols": (universe.get("funnel") or {}).get("shortlisted", 0),
            },
            "last_refresh_at": universe.get("last_scan_at"),
            "read_model_only": True,
        },
        "total_symbols": (universe.get("funnel") or {}).get("available", 0),
        "counts": universe.get("funnel"),
        "groups": {
            "crypto_universe": crypto,
            "stock_universe": stock,
            "active_push_pull_candidates": candidates,
        },
        "symbols": candidates,
        "top_blockers": universe.get("top_blockers") or [],
        "stale_reason": universe.get("stale_reason"),
    }


@router.get("/summary")
def universe_summary(session: Session = Depends(get_session)):
    """FAST READ-ONLY path for Universe top cards. Builds the funnel + cached source proof only
    (no heavy scan, no slow Alpaca discovery, no order path). Prefer this over /status, which runs
    the full mission-control build and can exceed the UI timeout (producing a false zero)."""
    from app.services.universe_summary_service import build_universe_summary

    return build_universe_summary(session)


@router.get("/scan-summary")
def scan_summary(session: Session = Depends(get_session)):
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: latest persisted scan summary.
    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "last_scan_at": universe.get("last_scan_at"),
        "counts": universe.get("funnel"),
        "top_blockers": universe.get("top_blockers") or [],
        "stale_reason": universe.get("stale_reason"),
    }


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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Full-pipeline endpoints (Caged Hive Quant Universe Radar)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/radar")
def radar(session: Session = Depends(get_session)):
    """Hybrid radar snapshot â€” full funnel, tiers, ranked, shortlist."""
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: latest persisted radar funnel. Use POST refresh for live scans.
    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "funnel": universe.get("funnel"),
        "shortlist": (st.get("eligible_entries_summary") or {}).get("top_candidates") or [],
        "block_breakdown": {
            b.get("code"): b.get("count") for b in universe.get("top_blockers") or [] if b.get("code")
        },
        "answer": (st.get("why_no_trade_summary") or {}).get("plain"),
        "stale_reason": universe.get("stale_reason"),
        "read_model_only": True,
    }


@router.get("/tiers")
def tiers(session: Session = Depends(get_session)):
    from app.services.hybrid_radar_service import universe_tiers

    return universe_tiers(session)


@router.get("/cache")
def cache(session: Session = Depends(get_session)):
    """Universe cache snapshot â€” counts, freshness, source metadata."""
    from app.services import symbol_identity_service
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "scan_summary": st.get("universe"),
        "symbol_identity_cache": symbol_identity_service.cache_snapshot(),
    }


@router.get("/rankings")
def rankings(session: Session = Depends(get_session)):
    """Fast universe radar funnel.

    GET is page-safe: it does not live-fetch every quote. Symbols may rank from
    cached bars, but execution still requires fresh quotes in the risk cage.
    Use POST /api/universe/refresh for an operator-triggered live rebuild.
    """
    from app.services.mission_control_read_model import build_mission_control_status

    # READ ONLY: latest ranked candidates from persisted scan/tick data.
    st = build_mission_control_status(session)
    universe = st.get("universe") or {}
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "ranked": universe.get("top_candidates") or [],
        "ranked_count": (universe.get("funnel") or {}).get("scored", 0),
        "top_blockers": universe.get("top_blockers") or [],
        "read_model_only": True,
    }


@router.get("/execution-shortlist")
def execution_shortlist(session: Session = Depends(get_session)):
    """Eligible paper entries â€” all symbols that pass gates (no shortlist cap)."""
    return _eligible_trades_payload(session)


@router.get("/eligible-trades")
def eligible_trades(session: Session = Depends(get_session)):
    """Canonical eligible-trades list for Universe UI and agent cycles."""
    return _eligible_trades_payload(session)


def _eligible_trades_payload(session: Session) -> dict:
    from app.services.mission_control_read_model import build_mission_control_status

    payload = build_mission_control_status(session)
    universe = payload.get("universe") or {}
    eligible = (payload.get("eligible_entries_summary") or {}).get("top_candidates") or []
    blockers = {b.get("code"): b.get("count") for b in universe.get("top_blockers") or [] if b.get("code")}
    scored = int((universe.get("funnel") or {}).get("scored") or 0)
    return {
        "status": payload.get("status") or "ok",
        "generated_at_utc": payload.get("generated_at_utc"),
        "answer": f"{len(eligible)} eligible from latest persisted scan." if eligible else "No eligible symbols this scan.",
        "block_breakdown": blockers,
        "eligible_trades": eligible,
        "shortlist": eligible,
        "strict_shortlist": [],
        "paper_exploration_shortlist": eligible,
        "shortlist_mode": "persisted_read_model",
        "trade_all_eligible": False,
        "execution_shortlist_count": len(eligible),
        "eligible_count": (universe.get("funnel") or {}).get("eligible", len(eligible)),
        "paper_exploration_shortlist_count": len(eligible),
        "scored_symbols": scored,
        "selected_candidate": eligible[0] if eligible else None,
        "no_trade_reason_breakdown": blockers,
        "why_zero_eligible": None
        if eligible
        else f"Latest persisted scan scored {scored} symbols; none are shortlisted. Blockers: {blockers}",
    }



@router.post("/refresh")
def refresh(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: force a universe pipeline rebuild + symbol identity cache refresh."""
    from app.services import symbol_identity_service
    from app.services.universe_strategy_discovery_service import build_funnel_breakdown

    symbol_identity_service.refresh_cache()
    return build_funnel_breakdown(session, max_evaluate=36, fetch_quotes=True)


@router.post("/score")
def score(
    body: dict = Body(default={}),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: score push-pull from cached/refreshed data."""
    from app.services.config_manager import ConfigManager
    from app.services.push_pull_scoring_service import score_active_universe

    limit = int((body or {}).get("limit") or 36)
    return score_active_universe(session, ConfigManager(session).get_current(), limit=limit)
