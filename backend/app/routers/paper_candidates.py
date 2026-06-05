"""Paper candidates status — shadow canary gate + alpha scorecard truth."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/paper-candidates", tags=["paper-candidates"])


@router.get("/status")
def paper_candidates_status(session: Session = Depends(get_session)):
    from app.services.paper_canary_gate_service import PaperCanaryGateService
    from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

    canary = PaperCanaryGateService(session).status()
    alpha = AutonomousAlphaFactoryService(session).get_status()
    return {
        "status": "ok",
        "paper_canary_gate": canary,
        "alpha_factory": {
            "paper_candidate_count": alpha.get("paper_candidate_count"),
            "can_trade_paper_now": alpha.get("can_trade_paper_now"),
            "best_candidate": alpha.get("best_candidate"),
            "reason": alpha.get("reason"),
        },
        "aggregate_gate_passed": canary.get("aggregate_gate_passed"),
        "live_trading_locked": True,
    }
