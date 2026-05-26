from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/ai-advisor", tags=["ai-advisor"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import ai_advisor_status

    return ai_advisor_status(session)


@router.get("/latest-review")
def latest_review(session: Session = Depends(get_session)):
    from app.services.sentiment_status_service import ai_advisor_status

    st = ai_advisor_status(session)
    return {"status": "ok", "latest_review": st.get("latest_review"), "advisor_active": st.get("advisor_active")}
