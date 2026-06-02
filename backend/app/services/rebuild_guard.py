"""Guard for the destructive /api/rebuild path (hard nuke + fresh paper cycles).

Refuses unless an explicit confirmation phrase is given, and — during an active validation run
(paper_validation_run_001) — an explicit override reason plus an acknowledgement that the paper
engines are stopped/safe to rebuild. On refusal the destructive rebuild is never reached, so
DangerZoneService.nuke_everything() is not called. Audits actor/reason/result (no secrets).
Never enables live trading.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

# Dedicated rebuild phrase (distinct from the danger-zone "NUKE CAGED HIVE" phrase, which is
# preserved for /api/danger-zone/nuke-everything).
REBUILD_CONFIRMATION_PHRASE = "REBUILD CAGED HIVE"


def _active_validation_run(session: Session) -> Optional[str]:
    try:
        from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch

        epoch = get_latest_reset_epoch(session) or {}
        return epoch.get("validation_run_id") or (PAPER_VALIDATION_RUN_ID if epoch else None)
    except Exception:
        return None


def evaluate_rebuild_request(
    session: Session,
    *,
    operator: str = "operator",
    confirmation_phrase: str = "",
    validation_run_override_reason: str = "",
    engines_stopped_ack: bool = False,
) -> dict[str, Any]:
    """Decide whether a destructive rebuild may proceed. Pure decision + audit; never destructive."""
    phrase_ok = str(confirmation_phrase or "").strip() == REBUILD_CONFIRMATION_PHRASE
    active_run = _active_validation_run(session)
    override_reason = str(validation_run_override_reason or "").strip()
    override_valid = bool(override_reason) and bool(engines_stopped_ack)

    refusal_codes: list[str] = []
    if not phrase_ok:
        refusal_codes.append("CONFIRMATION_PHRASE_REQUIRED")
    if active_run and not override_valid:
        refusal_codes.append("REBUILD_BLOCKED_DURING_VALIDATION")
        if not override_reason:
            refusal_codes.append("VALIDATION_RUN_OVERRIDE_REQUIRED")

    allowed = phrase_ok and (not active_run or override_valid)
    result = {
        "allowed": allowed,
        "active_validation_run_id": active_run,
        "confirmation_phrase_ok": phrase_ok,
        "validation_run_override_valid": (override_valid if active_run else None),
        "engines_stopped_ack": bool(engines_stopped_ack),
        "refusal_codes": refusal_codes,
        "required_confirmation_phrase": REBUILD_CONFIRMATION_PHRASE,
        "live_trading_locked": True,
    }
    _audit(session, operator=operator, reason=override_reason, result=result)
    return result


def rebuild_refusal_response(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "refused",
        "reason": "rebuild_guard_blocked",
        "refusal_codes": result.get("refusal_codes", []),
        "required_confirmation_phrase": REBUILD_CONFIRMATION_PHRASE,
        "active_validation_run_id": result.get("active_validation_run_id"),
        "how_to_proceed": (
            "Provide confirmation_phrase, and during an active validation run also "
            "validation_run_override_reason plus engines_stopped_ack=true after stopping the "
            "paper scheduler/engines."
        ),
        "live_trading_locked": True,
        "orders_created": 0,
        "nuke_called": False,
    }


def _audit(session: Session, *, operator: str, reason: str, result: dict[str, Any]) -> None:
    try:
        from app.services.activity_logger import log_activity

        log_activity(
            session,
            "rebuild_guard",
            "Rebuild request " + ("ALLOWED" if result.get("allowed") else "REFUSED"),
            {
                "operator": operator,
                "override_reason": (reason or "")[:200],
                "allowed": result.get("allowed"),
                "refusal_codes": result.get("refusal_codes"),
                "active_validation_run_id": result.get("active_validation_run_id"),
                "at": datetime.utcnow().isoformat() + "Z",
            },
        )
        try:
            session.flush()
        except Exception:
            pass
    except Exception:
        pass  # auditing must never block or break the guard decision
