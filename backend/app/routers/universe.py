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
