"""Single source of truth for autonomous paper-learning UI and safety banner."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.config_manager import ConfigManager
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.paper_learning_blockers import compute_push_pull_blockers


def paper_learning_display_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Push-pull paper learning truth — not legacy fast-training blockers."""
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

    cfg = config or ConfigManager(session).get_current()
    block = compute_push_pull_blockers(session, cfg)
    sched = AutonomousPaperScheduler(session, cfg).status()
    mode_on = bool(block.get("mode_enabled"))
    can_place = bool(block.get("can_place_paper_orders"))

    try:
        from app.services.safe_responses import safe_confidence_summary

        conf = safe_confidence_summary(session, cfg)
        if conf.get("status") == "degraded":
            conf = {
                "overall": None,
                "overall_label": "Unavailable",
                "confidence_state": "unavailable",
            }
    except Exception:
        conf = {
            "overall": None,
            "overall_label": "Unavailable",
            "confidence_state": "unavailable",
        }

    trip = live_lock_tripwire_status(cfg)
    recon = BrokerReconciliationService(session, cfg)
    ghosts = recon.ghost_position_candidates()
    broker_truth = "Synced" if not ghosts else "Needs Review"

    if not mode_on:
        current_mode = "paper_learning_off"
        plain = "Paper learning is OFF. Use Start Fresh Paper Learning on Mission Control."
    elif can_place:
        current_mode = "paper_learning"
        plain = (
            "Push-pull paper learning is ON. The bot may place small paper trades under strict limits. "
            "Live trading remains locked."
        )
    elif mode_on and sched.get("scheduler_enabled"):
        current_mode = "paper_learning"
        plain = "Paper learning is ON. Waiting for next push-pull tick or a stronger entry signal."
    else:
        current_mode = "paper_learning"
        plain = "Paper learning is ON but execution is blocked — see Mission Control for the exact reason."

    open_n = len(list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()))
    allocator = block.get("allocator") or {}

    return {
        "mode_enabled": mode_on,
        "paper_learning_on": mode_on,
        "can_place_paper_orders": can_place,
        "bot_can_place_paper_orders": can_place,
        "scheduler_enabled": bool(sched.get("scheduler_enabled")),
        "current_mode": current_mode,
        "liveTradingLocked": trip.get("live_lock_status") == "locked",
        "paperLearning": "ON" if mode_on else "OFF",
        "trainingMode": "ON" if mode_on else "OFF",
        "confidenceScore": conf.get("overall"),
        "confidenceLabel": conf.get("overall_label"),
        "confidence_state": conf.get("confidence_state"),
        "currentMode": current_mode,
        "botCanPlaceOrders": "YES" if can_place else "NO",
        "openPositions": open_n,
        "brokerTruth": broker_truth,
        "paperBroker": trip.get("paper_broker", True),
        "plainMessage": plain,
        "blockers": block.get("blockers_plain", []),
        "blocker_codes": block.get("blockers", []),
        "scheduler": sched,
        "learning_capacity": {
            "paper_trade_frequency": "opportunity_based",
            "daily_paper_trade_cap": "no_fixed_cap",
            "position_control": "allocator_exposure",
        },
        "capital_allocator": allocator,
    }
