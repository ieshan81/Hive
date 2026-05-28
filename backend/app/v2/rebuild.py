"""Hard nuke + full V2 rebuild — optimized for speed."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.danger_zone_service import DangerZoneService
from app.services.push_pull_strategy_seed import ensure_crypto_push_pull_baseline
from app.v2.aggressive_profile import aggressive_config_patch
from app.v2.agent_engine import run_agent_cycle
from app.v2.watchlist import BOOTSTRAP_CRYPTO, BOOTSTRAP_STOCKS, live_full_watchlist

logger = logging.getLogger("hive.v2.rebuild")


def _clear_runtime_caches() -> None:
    """Drop in-process caches so post-nuke reads are live Alpaca/DB truth."""
    try:
        from app.services import alpaca_adapter

        alpaca_adapter._SYNC_CACHE.clear()
    except Exception:
        pass
    try:
        from app.services import alpaca_crypto_assets

        alpaca_crypto_assets._CACHE["assets"] = {}
        alpaca_crypto_assets._CACHE["fetched_at"] = None
    except Exception:
        pass
    try:
        from app.services import radar_resilience

        radar_resilience._LAST_SUCCESS = {"at": None, "payload": None}
    except Exception:
        pass
    try:
        from app.services import mission_control_snapshot_service as mcs

        if hasattr(mcs, "_CACHE") and isinstance(mcs._CACHE, dict):
            mcs._CACHE.clear()
    except Exception:
        pass


def hard_nuke(session: Session, operator: str = "v2_rebuild") -> dict[str, Any]:
    """Wipe learned data + bars; keep schema and safety config shell."""
    _clear_runtime_caches()

    result = DangerZoneService(session).nuke_everything(operator=operator)
    try:
        session.commit()
    except Exception:
        session.rollback()
    return result


def apply_v2_profile(session: Session, operator: str = "v2_rebuild") -> dict[str, Any]:
    mgr = ConfigManager(session)
    cur = mgr.get_current()
    patch = aggressive_config_patch()
    proposal = mgr.propose(patch, changed_by=operator, reason="V2 aggressive research rebuild profile")
    active = mgr.activate_proposal(proposal.id)
    ensure_crypto_push_pull_baseline(session, mgr.get_current())
    return {"status": "ok", "config_version": active.version, "proposal_id": proposal.id}


def full_rebuild(session: Session, operator: str = "v2_rebuild") -> dict[str, Any]:
    """
    Hard nuke → aggressive profile → seed strategies → refresh major bars only →
    enable paper → run agent cycles (2x for first momentum).
    """
    started = datetime.utcnow().isoformat() + "Z"
    steps: list[dict[str, Any]] = []

    steps.append({"step": "nuke", "result": hard_nuke(session, operator)})
    steps.append({"step": "profile", "result": apply_v2_profile(session, operator)})

    from app.services.paper_learning_start_service import start_fresh_paper_learning

    steps.append({"step": "paper_learning", "result": start_fresh_paper_learning(session, operator=operator)})

    cfg = ConfigManager(session).get_current()
    from app.v2.agent_engine import refresh_watchlist_bars

    wl = live_full_watchlist(session, force=True)
    steps.append({"step": "watchlist", "result": {"total": wl.get("total"), "crypto": wl.get("crypto"), "stocks": wl.get("stocks")}})

    steps.append(
        {
            "step": "bars_refresh",
            "result": refresh_watchlist_bars(
                session,
                cfg,
                crypto_symbols=BOOTSTRAP_CRYPTO,
                stock_symbols=BOOTSTRAP_STOCKS,
                operator=operator,
            ),
        }
    )

    c1 = run_agent_cycle(session, operator=operator)
    steps.append({"step": "agent_cycle_1", "result": c1})
    c2 = run_agent_cycle(session, operator=operator)
    steps.append({"step": "agent_cycle_2", "result": c2})

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        steps.append({"step": "commit_error", "error": str(exc)[:300]})

    return {
        "status": "ok",
        "message": "Hard nuke complete. V2 aggressive agent is live on Alpaca paper.",
        "started_at": started,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "steps": steps,
        "final_cycle": c2,
        "can_trade": c2.get("can_place_paper_orders"),
        "blockers": c2.get("blockers"),
    }
