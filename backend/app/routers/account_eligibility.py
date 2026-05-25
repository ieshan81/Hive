"""Account / pair eligibility for paper trading."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/account-pair-eligibility", tags=["account-eligibility"])


@router.get("")
def account_pair_eligibility(session: Session = Depends(get_session)):
    from app.services.account_pair_eligibility_service import AccountPairEligibilityService

    return AccountPairEligibilityService(session).summary()
