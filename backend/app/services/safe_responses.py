"""Degraded API responses — never bare 500 for read endpoints."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.live_lock_tripwire import live_lock_tripwire_status


def _broker_read_meta(session: Session) -> dict[str, Any]:
    alpaca = AlpacaAdapter(session)
    snap = None
    try:
        snap = alpaca.sync_account_cached()
    except Exception as exc:
        return {
            "broker_status": "unavailable",
            "broker_sync_rate_limited": bool(alpaca.broker_sync_rate_limited),
            "data_freshness": "unknown",
            "message": str(exc)[:200],
        }
    if alpaca.broker_sync_rate_limited:
        status = "rate_limited"
        freshness = "stale_rate_limited"
    elif snap:
        status = "ok"
        freshness = "cached" if alpaca.broker_sync_rate_limited else "synced"
    else:
        status = "unavailable"
        freshness = "unknown"
    balances = {"USD": 0.0, "USDC": 0.0, "USDT": 0.0}
    if snap:
        balances["USD"] = max(float(snap.cash or 0), float(snap.buying_power or 0))
        raw = snap.raw_payload if isinstance(snap.raw_payload, dict) else {}
        for cur in ("USDC", "USDT"):
            val = raw.get(cur) or raw.get(f"{cur.lower()}_balance")
            if val is not None:
                try:
                    balances[cur] = float(val)
                except (TypeError, ValueError):
                    pass
    return {
        "broker_status": status,
        "broker_sync_rate_limited": bool(alpaca.broker_sync_rate_limited),
        "data_freshness": freshness,
        "cash": balances.get("USD"),
        "buying_power": float(snap.buying_power) if snap else None,
        "quote_balances": balances,
    }


def safe_account_pair_eligibility(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.account_pair_eligibility_service import AccountPairEligibilityService
    from app.services.config_manager import ConfigManager

    cfg = config or ConfigManager(session).get_current()
    broker = _broker_read_meta(session)
    try:
        if broker["broker_status"] == "unavailable":
            return {
                "status": "degraded",
                "paper_broker": True,
                **broker,
                "supported_quote_currencies": [],
                "eligible": [],
                "blocked": [],
                "eligible_count": 0,
                "blocked_count": 0,
                "plain_message": "Broker sync unavailable — pairs cannot be classified as tradeable.",
            }
        out = AccountPairEligibilityService(session, cfg).summary()
        out["broker_status"] = broker.get("broker_status", "ok")
        out["data_freshness"] = broker.get("data_freshness", "synced")
        if broker.get("broker_sync_rate_limited"):
            out["plain_message"] = "Broker sync temporarily rate-limited — using last known balances."
        return out
    except Exception as exc:
        return {
            "status": "degraded",
            "paper_broker": True,
            **broker,
            "eligible": [],
            "blocked": [],
            "eligible_count": 0,
            "blocked_count": 0,
            "error_type": type(exc).__name__,
            "message": str(exc)[:300],
            "plain_message": "Account pair eligibility temporarily unavailable.",
        }


def safe_confidence_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.confidence_engine import ConfidenceEngine
    from app.services.config_manager import ConfigManager

    cfg = config or ConfigManager(session).get_current()
    failed_buckets: list[str] = []
    try:
        data = ConfidenceEngine(session, cfg).summary()
        data["status"] = "ok"
        data["failed_buckets"] = failed_buckets
        data["broker_read"] = _broker_read_meta(session)
        return data
    except Exception as exc:
        trip = live_lock_tripwire_status(cfg)
        return {
            "status": "degraded",
            "overall": None,
            "overall_label": "Unavailable",
            "failed_buckets": ["all"],
            "error_type": type(exc).__name__,
            "message": str(exc)[:300],
            "can_unlock_live": False,
            "interpretation": "Confidence temporarily unavailable — not permission to trade live.",
            "live_lock_status": trip.get("live_lock_status"),
            "broker_read": _broker_read_meta(session),
            "dimensions": {},
        }


def safe_build_dashboard(session: Session) -> dict[str, Any]:
    from app.services.dashboard_service import build_dashboard

    try:
        data = build_dashboard(session)
        data["_api_status"] = "ok"
        return data
    except Exception as exc:
        from app.services.config_manager import ConfigManager
        from app.services.paper_learning_truth import paper_learning_display_status

        cfg = ConfigManager(session).get_current()
        trip = live_lock_tripwire_status(cfg)
        display = {}
        try:
            display = paper_learning_display_status(session, cfg)
        except Exception:
            display = {"paperLearning": "UNKNOWN", "plainMessage": "Paper learning status unavailable."}
        return {
            "_api_status": "degraded",
            "section_error": {
                "dashboard": type(exc).__name__,
                "message": str(exc)[:300],
                "traceback_summary": traceback.format_exc()[-1500:],
            },
            "safetyBanner": display,
            "live_lock": trip,
            "systemStatus": {
                "alpacaConnected": False,
                "geminiConfigured": False,
                "databaseConnected": True,
                "killSwitchActive": bool(cfg.get("kill_switch_active")),
                "paperTradingOnly": True,
                "liveTradingEnabled": False,
                "degraded": True,
            },
            "plain_message": "Dashboard partially unavailable — core safety state shown where possible.",
        }


def lightweight_dashboard_snapshot(session: Session) -> dict[str, Any]:
    """Read-mostly dashboard slice for diagnostic export — no build_dashboard / Alpaca sync storm."""
    from app.services.config_manager import ConfigManager
    from app.services.paper_learning_truth import paper_learning_display_status

    cfg = ConfigManager(session).get_current()
    trip = live_lock_tripwire_status(cfg)
    snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
    display = {}
    try:
        display = paper_learning_display_status(session, cfg)
    except Exception as exc:
        display = {"error": type(exc).__name__, "message": str(exc)[:200]}
    return {
        "status": "lightweight",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "safety_banner": display,
        "live_lock": trip,
        "account_snapshot": {
            "equity": float(snap.equity) if snap else None,
            "cash": float(snap.cash) if snap else None,
            "buying_power": float(snap.buying_power) if snap else None,
            "synced_at": snap.synced_at.isoformat() + "Z" if snap and snap.synced_at else None,
        }
        if snap
        else None,
        "note": "Full build_dashboard omitted from diagnostic export to reduce DB/Alpaca pressure.",
    }
