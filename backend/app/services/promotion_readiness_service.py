"""Live promotion checklist — evidence only; never enables live trading."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PromotionStatus, TradeRecord
from app.services.account_pair_eligibility_service import AccountPairEligibilityService
from app.services.broker_safety import is_paper_broker_url
from app.services.confidence_engine import ConfidenceEngine, can_unlock_live
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get, current_promotion_stage
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.promotion_service import PromotionService
from app.services.session_engine import SessionEngine


LIVE_STAGES = [
    "Paper Learning",
    "Paper Validated",
    "Tiny Live Candidate",
    "Tiny Live Active",
    "Standard Live Candidate",
    "Standard Live Active",
]


class PromotionReadinessService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.criteria = dict(self.config.get("promotion_readiness") or {})

    def checklist(self) -> dict[str, Any]:
        gaps: list[str] = []
        checks: dict[str, bool] = {}

        trip = live_lock_tripwire_status(self.config)
        checks["live_lock_locked"] = trip.get("live_lock_status") == "locked"
        if not checks["live_lock_locked"]:
            gaps.append("Live lock must remain locked during paper learning")

        checks["paper_broker"] = is_paper_broker_url()
        if not checks["paper_broker"]:
            gaps.append("Paper broker URL required")

        promo = PromotionService(self.session, self.config).status()
        row = self.session.get(PromotionStatus, 1)
        paper_started = row.paper_started_at if row else datetime.utcnow()
        min_days = int(self.criteria.get("min_paper_days", 7))
        days = (datetime.utcnow() - paper_started).days if paper_started else 0
        checks["min_paper_days"] = days >= min_days
        if not checks["min_paper_days"]:
            gaps.append(f"Need {min_days} paper days (have {days})")

        closed = list(self.session.exec(select(TradeRecord).where(TradeRecord.status == "closed")).all())
        min_trades = int(self.criteria.get("min_closed_paper_trades", 5))
        checks["min_closed_trades"] = len(closed) >= min_trades
        if not checks["min_closed_trades"]:
            gaps.append(f"Need {min_trades} closed paper trades (have {len(closed)})")

        conf = ConfidenceEngine(self.session, self.config).summary()
        overall_raw = conf.get("overall")
        overall = float(overall_raw) if overall_raw is not None else 0.0
        min_conf = float(self.criteria.get("min_confidence_for_tiny_live", 61))
        no_evidence = conf.get("confidence_state") == "no_evidence"
        checks["confidence_threshold"] = (not no_evidence) and overall >= min_conf
        if no_evidence:
            gaps.append("No post-reset paper evidence yet — confidence cannot support live promotion")
        elif not checks["confidence_threshold"]:
            gaps.append(f"Confidence {overall:.0f} below {min_conf}")

        sess = SessionEngine().detect()
        checks["market_calendar_ok"] = sess.calendar_available
        if not checks["market_calendar_ok"]:
            gaps.append("Market calendar unavailable")

        elig = AccountPairEligibilityService(self.session, self.config).summary()
        checks["pair_eligibility_ok"] = elig.get("blocked_count", 0) == 0 or elig.get("eligible_count", 0) > 0
        if elig.get("blocked_count", 0) > 10:
            gaps.append("Many pairs blocked by account balance")

        rets = [float(t.return_pct or 0) for t in closed if t.return_pct is not None]
        expectancy = sum(rets) / len(rets) if rets else 0
        checks["positive_expectancy"] = expectancy >= float(self.criteria.get("min_expectancy_pct", 0))
        if not checks["positive_expectancy"] and closed:
            gaps.append("Expectancy not positive enough")

        checks["can_unlock_live_via_confidence"] = can_unlock_live()
        checks["operator_confirm_required"] = True

        # operational_readiness_check (7d/5t) is an early signal only — it does NOT control
        # live/pre-live promotion. The pre-live REQUEST is gated by the STRICTER authoritative
        # promotion_to_pre_live_criteria (90d/100t), so a 7/5 system can never be "live-ready".
        from app.services.promotion_criteria import (
            authoritative_promotion_criteria,
            promotion_to_pre_live_criteria,
        )

        operational_ready = len(gaps) == 0
        pre = promotion_to_pre_live_criteria(self.config)
        pre_live_ready = days >= pre["min_calendar_days"] and len(closed) >= pre["min_closed_trades"]
        ready_for_tiny_live_request = operational_ready and pre_live_ready

        stage_idx = 0
        if current_promotion_stage(self.config) == "PAPER":
            stage_idx = 1 if operational_ready else 0

        return {
            "status": "ok",
            "live_promotion_locked": checks["live_lock_locked"],
            "criteria_source": "operational_readiness_check",
            "controls_live_pre_live_promotion": "promotion_to_pre_live_criteria",
            "operational_ready": operational_ready,
            "pre_live_ready": pre_live_ready,
            # ready_for_tiny_live_request now requires the STRICTER pre-live criteria, not just 7/5.
            "ready_for_tiny_live_request": ready_for_tiny_live_request,
            "authoritative_criteria": authoritative_promotion_criteria(self.config, session=self.session),
            "gaps": gaps,
            "checks": checks,
            "current_stage": promo.get("current_stage"),
            "live_stages": LIVE_STAGES,
            "current_stage_index": stage_idx,
            "confidence_overall": overall,
            "confidence_label": conf.get("overall_label"),
            "shift_to_live_allowed": False,
            "message": (
                "operational_readiness_check is an early signal; live/pre-live promotion is governed "
                "by the stricter promotion_to_pre_live_criteria. Shift to Live does not enable trading."
            ),
            "live_credentials_validation_places_orders": False,
        }

    def validate_live_credentials_locked(self) -> dict[str, Any]:
        """Validate credentials shape only — no live order."""
        from app.config import settings

        ok = bool(settings.alpaca_api_key and settings.alpaca_secret_key)
        return {
            "status": "ok" if ok else "error",
            "credentials_present": ok,
            "orders_placed": 0,
            "message": "Credential check only — no live order submitted.",
        }

    def request_shift_to_live(self, operator_note: str = "") -> dict[str, Any]:
        chk = self.checklist()
        if not chk.get("ready_for_tiny_live_request"):
            return {
                "status": "blocked",
                "message": "Promotion checklist not satisfied",
                "gaps": chk.get("gaps"),
                "orders_placed": 0,
            }
        return {
            **PromotionService(self.session, self.config).request_promotion("PRE_LIVE", operator_note=operator_note),
            "checklist": chk,
            "orders_placed": 0,
        }
