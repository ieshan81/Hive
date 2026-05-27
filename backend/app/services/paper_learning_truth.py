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
    """Push-pull paper learning truth — unified product_truth model."""
    from app.services.product_truth_service import product_truth

    cfg = config or ConfigManager(session).get_current()
    truth = product_truth(session, cfg)
    block = compute_push_pull_blockers(session, cfg)
    sched = truth.get("scheduler") or {}
    mode_on = bool(truth.get("operator_desired_paper_learning"))
    can_place = bool(truth.get("effective_can_place_paper_orders"))

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

    current_mode = truth.get("current_mode") or "off"
    plain = truth.get("operator_next_action") or ""
    if not mode_on:
        plain = "Paper learning is OFF. Use Start Fresh Paper Learning on Mission Control."
    elif can_place:
        plain = (
            "Push-pull paper learning is ON. The bot may place formula-sized paper trades through the cage. "
            "Live trading remains locked."
        )
    elif mode_on:
        plain = plain or "Paper learning is ON. Waiting for next push-pull tick or a stronger entry signal."

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
            "position_control": "formula_allocator",
        },
        "capital_allocator": allocator,
    }
