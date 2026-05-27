"""Fast cached page-state endpoints for frontend."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.page_state_service import PAGE_BUILDERS, get_page_state

router = APIRouter(prefix="/api/page-state", tags=["page-state"])


@router.get("/mission-control")
def mission_control(session: Session = Depends(get_session)):
    return get_page_state(session, "mission-control")


@router.get("/universe")
def universe(session: Session = Depends(get_session)):
    return get_page_state(session, "universe")


@router.get("/push-pull")
def push_pull(session: Session = Depends(get_session)):
    return get_page_state(session, "push-pull")


@router.get("/ai-manager")
def ai_manager(session: Session = Depends(get_session)):
    return get_page_state(session, "ai-manager")


@router.get("/hive-mind")
def hive_mind(session: Session = Depends(get_session)):
    return get_page_state(session, "hive-mind")


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)):
    return get_page_state(session, "portfolio")


@router.get("/performance")
def performance(session: Session = Depends(get_session)):
    return get_page_state(session, "performance")


@router.get("/activity")
def activity(session: Session = Depends(get_session)):
    return get_page_state(session, "activity")


@router.get("/reports")
def reports(session: Session = Depends(get_session)):
    return get_page_state(session, "reports")


@router.get("/control-center")
def control_center(session: Session = Depends(get_session)):
    return get_page_state(session, "control-center")
