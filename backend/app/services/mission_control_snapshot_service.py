"""Mission Control cached snapshot — fast status endpoint, heavy refresh in background."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.universe_mode_service import get_universe_mode

logger = logging.getLogger(__name__)

# In-process snapshot (single Railway worker; survives across requests on same instance).
_CACHE: dict[str, Any] = {
    "cockpit": None,
    "meta": {},
    "generated_at": None,
    "refreshed_at": None,
}
_REFRESH_LOCK = threading.Lock()
_REFRESH_IN_PROGRESS = False
_SNAPSHOT_TTL_SEC = 90
_FAST_BUILD_MAX_SEC = 0.85

_BUDGETS_MS = {
    "live_lock": 250,
    "account": 500,
    "universe": 500,
    "crypto": 500,
    "sentiment": 300,
    "memory": 300,
    "strategy": 500,
    "portfolio": 500,
    "product_truth": 400,
    "push_pull": 400,
}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _snapshot_age_seconds() -> Optional[float]:
    ts = _CACHE.get("generated_at")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return None


def _data_freshness_label(age: Optional[float]) -> str:
    if age is None:
        return "unknown"
    if age < 60:
        return "fresh"
    if age < 300:
        return "stale"
    return "very_stale"


def _run_bounded(
    name: str,
    fn: Callable[[], Any],
    budget_ms: int,
    *,
    default: Any = None,
) -> tuple[Any, bool, Optional[str]]:
    """Run fn with timeout; return (result, ok, error_reason)."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(fn)
        out = fut.result(timeout=budget_ms / 1000.0)
        return out, True, None
    except FuturesTimeout:
        logger.warning("mission_control subsystem timeout: %s (%sms)", name, budget_ms)
        return default, False, f"{name}_timeout"
    except Exception as exc:
        logger.warning("mission_control subsystem error: %s %s", name, exc)
        return default, False, f"{name}_error"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _subsystem_live_lock(cfg: dict) -> dict[str, Any]:
    lock = live_lock_tripwire_status(cfg)
    return {
        "status": lock.get("live_lock_status", "locked"),
        "fresh": True,
        "live_trading_enabled": False,
        "paper_broker": bool(lock.get("paper_broker")),
    }


def _subsystem_universe_fast(session: Session, cfg: dict) -> dict[str, Any]:
    from app.services.radar_resilience import last_successful_scan, minimal_radar_counts

    mode = get_universe_mode(cfg)
    counts = minimal_radar_counts(session, cfg)
    cached = last_successful_scan()
    if cached.get("cached_snapshot_available"):
        from app.services.radar_resilience import _LAST_SUCCESS

        payload = _LAST_SUCCESS.get("payload") or {}
        counts = {**counts, **(payload.get("counts") or {})}
    return {
        "status": "ok",
        "mode": mode,
        "available_symbols": counts.get("available_usd_pairs", 0),
        "eligible": counts.get("eligible", 0),
        "cached_data_used": bool(cached.get("cached_snapshot_available")),
        "fresh": cached.get("cached_snapshot_available", False),
        "reason": None,
    }


def _subsystem_crypto_fast(session: Session, cfg: dict) -> dict[str, Any]:
    from app.services.radar_resilience import last_successful_scan

    uni = _subsystem_universe_fast(session, cfg)
    cached = last_successful_scan()
    paper_ok = bool(
        uni.get("eligible", 0) > 0
        and cached.get("cached_snapshot_available")
    )
    return {
        "status": "ok" if paper_ok else "degraded",
        "crypto_24_7_active": True,
        "paper_trade_allowed": paper_ok,
        "cached_data_used": bool(cached.get("cached_snapshot_available")),
        "fresh": cached.get("cached_snapshot_available", False),
        "reason": None if paper_ok else "freshness_not_proven",
    }


def _subsystem_sentiment_fast(session: Session, cfg: dict) -> dict[str, Any]:
    from app.services.finbert_client import finbert_service_url

    url = bool(finbert_service_url())
    return {
        "status": "ok" if url else "degraded",
        "finbert": {
            "active": url,
            "implemented": True,
            "worker_url_configured": url,
            "fresh": url,
        },
        "sentiment_can_place_trades": False,
        "fresh": url,
    }


def _subsystem_memory_fast(session: Session) -> dict[str, Any]:
    from sqlmodel import func, select

    from app.database import LessonNode
    from app.services.memory_policy_service import MemoryPolicyService

    mem = MemoryPolicyService(session).status()
    count = session.exec(select(func.count()).select_from(LessonNode)).one()
    return {
        "status": "ok",
        "meaningful_memory_count": mem.get("counts", {}).get("meaningful_memory_count", 0),
        "validated_count": mem.get("counts", {}).get("validated_count", 0),
        "fresh": True,
        "lesson_count": int(count or 0),
    }


def _subsystem_account_fast(session: Session, cfg: dict) -> dict[str, Any]:
    from app.services.mission_control_service import _account_truth

    acct = _account_truth(session, cfg)
    return {
        "status": "ok",
        "fresh": acct.get("broker_sync_status") == "synced",
        "account": acct,
    }


def _subsystem_product_truth_fast(session: Session, cfg: dict) -> dict[str, Any]:
    env = env_pause_status()
    lock = live_lock_tripwire_status(cfg)
    apl = dict(cfg.get("autonomous_paper_learning") or {})
    desired_learning = bool(apl.get("mode_enabled"))
    desired_execution = bool((cfg.get("execution") or {}).get("paper_orders_enabled"))
    from app.services.entry_safety_service import entry_safety_status

    safety = entry_safety_status(session, cfg)
    can_place = (
        desired_learning
        and desired_execution
        and not env.get("any_env_pause")
        and lock.get("live_lock_status") == "locked"
        and safety.get("new_paper_entries_allowed")
    )
    mode = "push_pull_paper_learning" if can_place else (
        "push_pull_scanning" if desired_learning else "paper_learning_off"
    )
    return {
        "status": "ok",
        "live_lock_status": lock.get("live_lock_status"),
        "paper_broker_status": "paper" if lock.get("paper_broker") else "unknown",
        "effective_can_place_paper_orders": can_place,
        "current_mode": mode,
        "current_mode_label": mode.replace("_", " ").title(),
        "primary_blocker": "ready" if can_place else "blocked",
        "primary_blocker_plain": (
            safety.get("operator_message")
            if not can_place
            else "Push-pull paper learning is active."
        ),
        "entry_safety": safety,
        "operator_desired_paper_learning": desired_learning,
        "env_pause_status": env,
        "fresh": True,
    }


def _build_fast_cockpit(session: Session, cfg: dict) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build minimal cockpit under ~1s — no live scans, graphs, or reconciliation."""
    warnings: list[str] = []
    degraded: list[str] = []

    truth, ok, err = _run_bounded(
        "product_truth",
        lambda: _subsystem_product_truth_fast(session, cfg),
        _BUDGETS_MS["product_truth"],
        default={},
    )
    if not ok:
        degraded.append("product_truth")
        truth = _subsystem_product_truth_fast(session, cfg)

    lock, ok_l, _ = _run_bounded(
        "live_lock",
        lambda: _subsystem_live_lock(cfg),
        _BUDGETS_MS["live_lock"],
        default={"status": "locked", "fresh": False, "paper_broker": True},
    )
    if not ok_l:
        degraded.append("live_lock")

    universe, ok_u, _ = _run_bounded(
        "universe",
        lambda: _subsystem_universe_fast(session, cfg),
        _BUDGETS_MS["universe"],
        default={"status": "degraded", "mode": "hybrid_radar", "available_symbols": 0},
    )
    if not ok_u or universe.get("status") != "ok":
        degraded.append("universe")
        warnings.append("Mission Control used cached universe snapshot")

    crypto, ok_c, _ = _run_bounded(
        "crypto",
        lambda: _subsystem_crypto_fast(session, cfg),
        _BUDGETS_MS["crypto"],
        default={"status": "degraded", "paper_trade_allowed": False},
    )
    if not ok_c or crypto.get("status") != "ok":
        degraded.append("crypto")
        if crypto.get("reason"):
            warnings.append(f"Crypto readiness: {crypto.get('reason')}")

    sentiment, ok_s, _ = _run_bounded(
        "sentiment",
        lambda: _subsystem_sentiment_fast(session, cfg),
        _BUDGETS_MS["sentiment"],
        default={"status": "degraded", "finbert": {"active": False}},
    )
    if not ok_s:
        degraded.append("sentiment")

    memory, ok_m, _ = _run_bounded(
        "memory",
        lambda: _subsystem_memory_fast(session),
        _BUDGETS_MS["memory"],
        default={"status": "degraded"},
    )
    if not ok_m:
        degraded.append("memory")

    account, ok_a, _ = _run_bounded(
        "account",
        lambda: _subsystem_account_fast(session, cfg),
        _BUDGETS_MS["account"],
        default={"status": "degraded", "account": {}},
    )
    if not ok_a:
        degraded.append("account")
        warnings.append("Account summary used cached broker snapshot")

    acct = account.get("account") or {}
    env = truth.get("env_pause_status") or {}

    cockpit = {
        "status": "degraded" if degraded else "ok",
        **truth,
        "cockpit_bar": {
            "live_trading": "Locked",
            "paper_learning": "On" if truth.get("operator_desired_paper_learning") else "Off",
            "current_mode": truth.get("current_mode_label"),
            "confidence": "—",
            "broker_sync": acct.get("broker_sync_status"),
            "paper_broker": truth.get("paper_broker_status"),
            "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
            "last_sync_at": acct.get("synced_at"),
        },
        "mission_summary": {
            "headline": truth.get("primary_blocker_plain") or "Mission Control snapshot",
            "engine_doing": "Cached snapshot — use Refresh for full cockpit rebuild.",
            "scans_on_schedule": truth.get("operator_desired_paper_learning"),
            "entries_allowed": truth.get("effective_can_place_paper_orders"),
            "exits_monitored": False,
            "learning_recording": memory.get("validated_count", 0) > 0,
            "broker_sync_healthy": acct.get("broker_sync_status") == "synced",
        },
        "account_survival": acct,
        "universe_mode": {
            "active_mode": universe.get("mode"),
            "mode_label": "Hybrid Radar",
            "display_counts": {"total": universe.get("available_symbols", 0)},
        },
        "ai_fund_manager": {
            "active": sentiment.get("finbert", {}).get("active"),
            "configured": sentiment.get("finbert", {}).get("worker_url_configured"),
            "sentiment_engines": {"finbert": sentiment.get("finbert")},
        },
        "live_lock": lock,
        "can_place_paper_orders": truth.get("effective_can_place_paper_orders"),
        "primary_blocker_plain": truth.get("primary_blocker_plain"),
        "capital_allocator": {"status": "cached", "headline": "Refresh for live allocator"},
        "market_radar": {"top_active_candidates": []},
        "hive_brain_preview": {
            "meaningful_memory_count": memory.get("meaningful_memory_count", 0),
            "validated_count": memory.get("validated_count", 0),
        },
        "snapshot_meta": {
            "build": "fast",
            "degraded_subsystems": degraded,
        },
    }
    return cockpit, warnings, degraded


def _wrap_status_response(cockpit: dict[str, Any], *, warnings: list[str], degraded: list[str]) -> dict[str, Any]:
    age = _snapshot_age_seconds()
    freshness = _data_freshness_label(age)
    overall = "degraded" if degraded or freshness in ("stale", "very_stale") else cockpit.get("status", "ok")
    if freshness == "very_stale":
        overall = "degraded"

    lock = cockpit.get("live_lock") or {}
    uni_mode = cockpit.get("universe_mode") or {}
    finbert = (cockpit.get("ai_fund_manager") or {}).get("sentiment_engines", {}).get("finbert", {})

    paper_allowed = bool(cockpit.get("can_place_paper_orders")) and overall == "ok" and freshness == "fresh"

    next_refresh = None
    if _CACHE.get("generated_at"):
        try:
            dt = datetime.fromisoformat(str(_CACHE["generated_at"]).replace("Z", "+00:00"))
            next_refresh = (dt + timedelta(seconds=_SNAPSHOT_TTL_SEC)).isoformat().replace("+00:00", "Z")
        except Exception:
            pass

    return {
        "status": overall,
        "generated_at_utc": _CACHE.get("generated_at") or _now(),
        "snapshot_age_seconds": round(age, 1) if age is not None else None,
        "data_freshness": freshness,
        "degraded": bool(degraded) or overall == "degraded",
        "missing_subsystem_warnings": warnings,
        "warnings": warnings,
        "degraded_subsystems": degraded,
        "last_successful_refresh": _CACHE.get("refreshed_at"),
        "next_refresh_at": next_refresh,
        "refresh_in_progress": _REFRESH_IN_PROGRESS,
        "live_lock": {
            "status": lock.get("status", lock.get("live_lock_status", "locked")),
            "fresh": lock.get("fresh", True),
        },
        "paper_broker": lock.get("paper_broker", True),
        "mode": uni_mode.get("active_mode") or "hybrid_radar",
        "finbert": {
            "active": finbert.get("active", False),
            "fresh": finbert.get("fresh", False),
        },
        "universe": {
            "status": "degraded" if "universe" in degraded else "ok",
            "available_symbols": (uni_mode.get("display_counts") or {}).get("total", 0),
            "cached_data_used": True,
            "reason": "cached_snapshot" if "universe" in degraded else None,
        },
        "crypto": {
            "status": "degraded" if "crypto" in degraded else "ok",
            "paper_trade_allowed": paper_allowed,
            "reason": "freshness_not_proven" if not paper_allowed else None,
        },
        "paper_trade_allowed": paper_allowed,
        "reason": "stale_snapshot" if overall == "degraded" and freshness != "fresh" else None,
        **cockpit,
    }


def _ensure_snapshot(session: Session) -> dict[str, Any]:
    age = _snapshot_age_seconds()
    if _CACHE.get("cockpit") and age is not None and age < _SNAPSHOT_TTL_SEC:
        return _CACHE["cockpit"]

    started = time.monotonic()
    cfg = ConfigManager(session).get_current()
    cockpit, warnings, degraded = _build_fast_cockpit(session, cfg)
    if time.monotonic() - started > _FAST_BUILD_MAX_SEC:
        degraded = list(set(degraded + ["fast_build_slow"]))
        warnings.append("Fast snapshot build exceeded budget — some subsystems skipped")

    _CACHE["cockpit"] = cockpit
    _CACHE["generated_at"] = _now()
    _CACHE["meta"] = {"warnings": warnings, "degraded": degraded, "build": "fast"}
    if not _CACHE.get("refreshed_at"):
        _CACHE["refreshed_at"] = _CACHE["generated_at"]
    return cockpit


def mission_control_status_fast(session: Session) -> dict[str, Any]:
    """Read-only fast path — never blocks on heavy cockpit build."""
    cockpit = _ensure_snapshot(session)
    meta = _CACHE.get("meta") or {}
    return _wrap_status_response(
        cockpit,
        warnings=list(meta.get("warnings") or []),
        degraded=list(meta.get("degraded") or []),
    )


def _refresh_worker(session_factory: Callable[[], Session]) -> None:
    global _REFRESH_IN_PROGRESS
    warnings: list[str] = []
    degraded: list[str] = []
    try:
        session = session_factory()
        cfg = ConfigManager(session).get_current()

        def _full_cockpit() -> dict[str, Any]:
            from app.services.mission_control_cockpit_service import mission_control_cockpit

            return mission_control_cockpit(session, cfg)

        cockpit, ok, err = _run_bounded(
            "full_cockpit",
            _full_cockpit,
            25000,
            default=None,
        )
        if not ok or not cockpit:
            degraded.append("full_refresh")
            warnings.append(err or "full_cockpit_timeout")
            cockpit, w2, d2 = _build_fast_cockpit(session, cfg)
            warnings.extend(w2)
            degraded.extend(d2)
        else:
            warnings.append("Full cockpit refresh completed")

        _CACHE["cockpit"] = cockpit
        _CACHE["generated_at"] = _now()
        _CACHE["refreshed_at"] = _now()
        _CACHE["meta"] = {"warnings": warnings, "degraded": degraded, "build": "full" if ok else "fast_fallback"}
    except Exception as exc:
        logger.exception("mission_control refresh failed: %s", exc)
        _CACHE["meta"] = {
            "warnings": [f"refresh_failed:{type(exc).__name__}"],
            "degraded": ["refresh"],
            "build": "error",
        }
    finally:
        _REFRESH_IN_PROGRESS = False
        try:
            session.close()
        except Exception:
            pass


def refresh_mission_control_snapshot(session: Session, *, background: bool = True) -> dict[str, Any]:
    """Rebuild snapshot; optional background thread to avoid blocking HTTP."""
    global _REFRESH_IN_PROGRESS

    if _REFRESH_IN_PROGRESS:
        return {
            "status": "ok",
            "refresh_in_progress": True,
            "message": "Refresh already running — returning current snapshot.",
            "snapshot": mission_control_status_fast(session),
        }

    from app.database import engine

    def _factory() -> Session:
        return Session(engine)

    if background:
        if not _REFRESH_LOCK.acquire(blocking=False):
            return {
                "status": "ok",
                "refresh_in_progress": True,
                "message": "Refresh already running.",
            }
        try:
            _REFRESH_IN_PROGRESS = True
            t = threading.Thread(target=_refresh_worker, args=(_factory,), daemon=True)
            t.start()
            return {
                "status": "ok",
                "refresh_in_progress": True,
                "message": "Background refresh started.",
                "generated_at_utc": _now(),
            }
        finally:
            _REFRESH_LOCK.release()
    else:
        _REFRESH_IN_PROGRESS = True
        _refresh_worker(_factory)
        return {
            "status": "ok",
            "refresh_in_progress": False,
            "message": "Synchronous refresh completed.",
            "snapshot": mission_control_status_fast(session),
        }


def reset_cache_for_tests() -> None:
    global _REFRESH_IN_PROGRESS
    _CACHE.clear()
    _CACHE.update({"cockpit": None, "meta": {}, "generated_at": None, "refreshed_at": None})
    _REFRESH_IN_PROGRESS = False
