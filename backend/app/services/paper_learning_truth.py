"""Single source of truth for autonomous paper-learning UI and safety banner."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.confidence_engine import ConfidenceEngine
from app.services.live_lock_tripwire import live_lock_tripwire_status


def paper_learning_display_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Single source for SafetyBanner, dashboard safetyBanner, and autonomous status API."""
    from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
    from app.services.config_manager import ConfigManager
    from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop

    cfg = config or ConfigManager(session).get_current()
    apl_cfg = dict(cfg.get("autonomous_paper_learning") or {})
    mode_on = bool(apl_cfg.get("mode_enabled"))
    ft_st = FastCryptoTrainingLoop(session, cfg).status()
    sched = AutonomousPaperScheduler(session, cfg).status()
    can_place = mode_on and bool(ft_st.get("final_can_submit_orders"))
    blockers = list(ft_st.get("blockers") or [])
    if mode_on and AlpacaAdapter(session).broker_sync_rate_limited:
        blockers = list(dict.fromkeys(blockers + ["broker_sync_rate_limited"]))
        can_place = False

    conf = ConfidenceEngine(session, cfg).summary()
    trip = live_lock_tripwire_status(cfg)
    recon = BrokerReconciliationService(session, cfg)
    ghosts = recon.ghost_position_candidates()
    broker_truth = "Synced" if not ghosts else "Needs Review"
    if AlpacaAdapter(session).broker_sync_rate_limited:
        broker_truth = "Broker sync temporarily rate-limited"

    current_mode = "watching"
    if not mode_on:
        current_mode = "watching"
    elif sched.get("scheduler_enabled") and not sched.get("paused"):
        current_mode = "paper_learning"
    else:
        current_mode = "paper_learning"

    if not mode_on:
        plain = "The bot is watching only. It cannot place paper orders."
    elif can_place:
        plain = (
            "The bot may place small paper trades under strict safety limits. Live trading remains locked."
        )
    else:
        plain = "Paper learning is on but preflight blockers prevent new orders right now."

    open_n = len(list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()))

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
        "currentMode": current_mode,
        "botCanPlaceOrders": "YES" if can_place else "NO",
        "openPositions": open_n,
        "brokerTruth": broker_truth,
        "paperBroker": trip.get("paper_broker", True),
        "plainMessage": plain,
        "blockers": blockers,
        "scheduler": sched,
    }
