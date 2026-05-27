"""Fast cached page-state payloads for frontend — never block on heavy scans."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.entry_safety_service import entry_safety_status
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.mission_control_snapshot_service import mission_control_status_fast
from app.services.radar_resilience import _LAST_SUCCESS, last_successful_scan, minimal_radar_counts
from app.services.reddit_scanner_service import reddit_status
from app.services.system_db_pool_service import db_pool_status
from app.services.universe_mode_service import get_universe_mode

logger = logging.getLogger(__name__)

_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_TTL_SEC = 45


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _age_seconds(generated_at: Optional[str]) -> Optional[float]:
    if not generated_at:
        return None
    try:
        dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return None


def _freshness(age: Optional[float]) -> str:
    if age is None:
        return "unknown"
    if age < 60:
        return "fresh"
    if age < 300:
        return "stale"
    return "very_stale"


def _envelope(
    payload: dict[str, Any],
    *,
    warnings: Optional[list[str]] = None,
    missing_sections: Optional[list[str]] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    gen = generated_at or _now()
    age = _age_seconds(gen)
    fresh = _freshness(age)
    missing = missing_sections or []
    warns = warnings or []
    status = payload.get("status", "ok")
    if missing or fresh in ("stale", "very_stale"):
        status = "degraded" if status == "ok" else status
    return {
        "status": status,
        "generated_at_utc": gen,
        "snapshot_age_seconds": round(age, 1) if age is not None else None,
        "data_freshness": fresh,
        "warnings": warns,
        "missing_sections": missing,
        "cached_data_used": payload.get("cached_data_used", True),
        **payload,
    }


def _cached_get(key: str, builder: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and (time.time() - entry.get("_ts", 0)) < _TTL_SEC:
            return entry["data"]
    try:
        data = builder()
    except Exception as exc:
        logger.warning("page_state %s failed: %s", key, exc)
        data = {"status": "degraded", "error": type(exc).__name__, "message": str(exc)[:200]}
    with _CACHE_LOCK:
        _CACHE[key] = {"_ts": time.time(), "data": data}
    return data


def page_state_mission_control(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        mc = mission_control_status_fast(session)
        safety = entry_safety_status(session)
        missing: list[str] = []
        acct = mc.get("account_survival") or {}
        alloc = mc.get("capital_allocator") or {}
        if not acct.get("equity") and acct.get("equity") != 0:
            missing.append("account_survival")
        if alloc.get("status") == "cached":
            missing.append("capital_allocator_live")
        cards = {
            "deployable": {
                "value": alloc.get("deployable_capital") or alloc.get("headline"),
                "reason": None if alloc.get("deployable_capital") else "Allocator snapshot stale — refresh Mission Control",
            },
            "cash_reserve": {
                "value": alloc.get("cash_reserve_pct") or acct.get("cash_reserve_pct"),
                "reason": None if alloc.get("cash_reserve_pct") else "Account snapshot unavailable",
            },
            "crypto_budget": {
                "value": alloc.get("crypto_budget"),
                "reason": None if alloc.get("crypto_budget") is not None else "Allocator degraded",
            },
            "stock_budget": {
                "value": alloc.get("stock_budget"),
                "reason": None if alloc.get("stock_budget") is not None else "Stock session closed or allocator stale",
            },
            "execution_shortlist": {
                "value": (mc.get("market_radar") or {}).get("top_active_candidates"),
                "reason": "Freshness not proven or shortlist empty" if not (mc.get("market_radar") or {}).get("top_active_candidates") else None,
            },
            "strategy_verdict": {
                "value": mc.get("primary_blocker_plain"),
                "reason": None,
            },
            "latest_tick": {
                "value": (mc.get("latest_insight") or {}).get("narrative"),
                "reason": "Latest tick unavailable in fast snapshot" if not (mc.get("latest_insight") or {}).get("narrative") else None,
            },
            "market_radar": {
                "value": mc.get("universe", {}).get("available_symbols"),
                "reason": "Using cached universe count" if mc.get("universe", {}).get("cached_data_used") else None,
            },
        }
        return _envelope(
            {
                "mission_control": mc,
                "entry_safety": safety,
                "cards": cards,
                "banner": (
                    "Using cached snapshot — some subsystems degraded."
                    if mc.get("degraded") or mc.get("data_freshness") != "fresh"
                    else None
                ),
                "new_paper_entries_allowed": safety.get("new_paper_entries_allowed"),
                "exit_monitor_active": safety.get("exit_monitor_active"),
            },
            warnings=mc.get("warnings") or [],
            missing_sections=missing,
            generated_at=mc.get("generated_at_utc"),
        )

    return _cached_get("mission-control", build)


def page_state_universe(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        cfg = ConfigManager(session).get_current()
        mode = get_universe_mode(cfg)
        cached = _LAST_SUCCESS.get("payload") or {}
        counts = cached.get("counts") or minimal_radar_counts(session, cfg)
        pipe = cached.get("pipeline") or {}
        funnel = pipe.get("funnel") or {
            "available": counts.get("available_usd_pairs") or counts.get("cached_usd_pairs") or 0,
            "cached": counts.get("cached_usd_pairs") or counts.get("available_usd_pairs") or 0,
            "eligible": counts.get("eligible", 0),
            "ranked": counts.get("ranked", 0),
            "execution_shortlist": counts.get("execution_shortlist", 0),
        }
        if funnel.get("available", 0) == 0 and counts.get("available_usd_pairs"):
            funnel["available"] = counts["available_usd_pairs"]
            funnel["cached"] = counts.get("cached_usd_pairs", counts["available_usd_pairs"])

        from app.services.alpaca_crypto_assets import fetch_crypto_assets

        assets = fetch_crypto_assets(force=False) or {}
        usd_pairs = sorted(s for s in assets.keys() if s.endswith("/USD"))
        symbols_table = []
        for sym in (usd_pairs or [])[:36]:
            symbols_table.append(
                {
                    "symbol": sym,
                    "asset_type": "Crypto",
                    "status": "Cached",
                    "tier": (cached.get("tier_samples") or {}).get(sym, "—"),
                    "bar_freshness": "cached",
                    "quote_freshness": "cached",
                    "block_reason": None,
                }
            )
        if cached.get("ranked_candidates"):
            symbols_table = [
                {
                    "symbol": r.get("symbol"),
                    "asset_type": "Crypto",
                    "status": "Ranked" if not r.get("dropped") else "Blocked",
                    "universe_rank_score": r.get("universe_rank_score"),
                    "block_reason": r.get("blocked_reason"),
                }
                for r in cached["ranked_candidates"][:36]
                if r.get("symbol")
            ] or symbols_table

        scan = last_successful_scan()
        return _envelope(
            {
                "active_mode": mode,
                "mode_label": "Hybrid Radar",
                "funnel": funnel,
                "counts": counts,
                "symbols": symbols_table,
                "lesser_known_highlights": cached.get("lesser_known_highlights") or [],
                "source_proof": {
                    "alpaca_crypto_api": "connected" if usd_pairs else "degraded",
                    "api_called": bool(scan.get("last_successful_scan")),
                    "last_successful_scan": scan.get("last_successful_scan"),
                    "cached_snapshot_available": scan.get("cached_snapshot_available"),
                    "usd_pair_count": len(usd_pairs),
                    "curated_crypto_displayed": len(symbols_table),
                },
                "cached_data_used": True,
                "reason": cached.get("reason") or ("no_live_refresh" if not scan.get("last_successful_scan") else None),
            },
            warnings=["Showing cached radar snapshot — live refresh not run on this request"] if not scan.get("last_successful_scan") else [],
            missing_sections=[] if funnel.get("available") else ["live_funnel"],
        )

    return _cached_get("universe", build)


def page_state_push_pull(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        cfg = ConfigManager(session).get_current()
        safety = entry_safety_status(session)
        missing: list[str] = []
        tick: dict[str, Any] = {}
        proof: dict[str, Any] = {}
        try:
            from app.services.push_pull_engine_service import PushPullEngineService

            eng = PushPullEngineService(session, cfg)
            tick = eng.latest_tick() or {}
        except Exception:
            missing.append("latest_tick")
        try:
            from app.services.paper_order_proof_service import PaperOrderProofService

            proof = PaperOrderProofService(session, cfg).summary()
        except Exception:
            missing.append("paper_order_proof")

        lessons: list[dict] = []
        try:
            from app.services.memory_policy_service import MemoryPolicyService

            mem_st = MemoryPolicyService(session).status()
            lu = mem_st.get("latest_useful_lesson")
            if lu:
                lessons = [lu]
        except Exception:
            missing.append("lessons")

        return _envelope(
            {
                "symbols_scanned": tick.get("symbols_scanned_count"),
                "fresh_bars": tick.get("fresh_bars_count"),
                "stale_bars": tick.get("stale_bars_count"),
                "candidates_ranked": tick.get("candidates_ranked"),
                "top_candidate": tick.get("top_candidate"),
                "why_blocked": tick.get("primary_blocker") or tick.get("plain"),
                "no_trade_reasons": tick.get("no_trade_reasons") or [],
                "next_action": (
                    "Refresh quotes and wait for fresh bars"
                    if safety.get("new_paper_entries_allowed") is False
                    else tick.get("next_action") or "Monitor push-pull scan"
                ),
                "paper_order_proof": proof,
                "latest_tick": tick,
                "lessons": lessons,
                "entry_safety": safety,
                "experiments": [
                    "Run HYPE/RENDER targeted experiment",
                    "POST /api/research/targeted-experiment/run",
                ],
            },
            missing_sections=missing,
            warnings=safety.get("warnings") or [],
        )

    return _cached_get("push-pull", build)


def page_state_ai_manager(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        missing: list[str] = []
        finbert: dict[str, Any] = {}
        scanners: dict[str, Any] = {}
        try:
            from app.services.sentiment_status_service import sentiment_status

            st = sentiment_status(session)
            finbert = st.get("finbert") or {}
        except Exception as exc:
            missing.append("sentiment")
            finbert = {"active": False, "error": str(exc)[:80]}
        try:
            from app.services import scanner_stack

            scanners = {
                "status": "ok",
                "scanners": scanner_stack.list_scanners(),
                "health": scanner_stack.health_snapshot(),
                "latest": scanner_stack.latest_outputs(),
            }
        except Exception:
            missing.append("scanners")
            scanners = {"status": "not_run", "message": "Not run since reset"}

        reddit = reddit_status()
        return _envelope(
            {
                "finbert": finbert,
                "sentiment_active": bool(finbert.get("active")),
                "scanner_stack": scanners,
                "reddit": reddit,
                "scanner_message": scanners.get("plain") or scanners.get("message") or "See scanner status",
            },
            missing_sections=missing,
        )

    return _cached_get("ai-manager", build)


def page_state_hive_mind(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        cfg = ConfigManager(session).get_current()
        graph: dict[str, Any] = {}
        missing: list[str] = []
        try:
            from app.services.hive_brain_graph_service import HiveBrainGraphService

            graph = HiveBrainGraphService(session, cfg).build_full(graph_mode="research")
        except Exception as exc:
            missing.append("graph")
            graph = {
                "status": "degraded",
                "message": "Research skeleton shown — graph build failed",
                "nodes": [],
                "edges": [],
                "error": str(exc)[:120],
            }
        lessons_count = 0
        try:
            from app.services.memory_policy_service import MemoryPolicyService

            mem_st = MemoryPolicyService(session).status()
            lessons_count = (mem_st.get("counts") or {}).get("meaningful_memory_count", 0)
        except Exception:
            pass
        return _envelope(
            {
                "graph": graph,
                "graph_mode": "research",
                "learned_memory_nodes": graph.get("learned_memory_nodes", 0),
                "meaningful_memory_count": lessons_count,
                "headline": (
                    "No validated trade memories yet. Research memories and system graph are shown."
                    if lessons_count == 0
                    else f"{lessons_count} research/lesson nodes available"
                ),
                "hive_mind_api_status": "ok",
            },
            missing_sections=missing,
            warnings=["Graph served from skeleton/research mode"] if graph.get("status") == "degraded" else [],
        )

    return _cached_get("hive-mind", build)


def page_state_portfolio(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        missing: list[str] = []
        positions: list = []
        orders: list = []
        recon: dict = {}
        try:
            from app.services.positions_tab_service import current_positions

            positions = current_positions(session) or []
        except Exception:
            missing.append("positions")
        try:
            from sqlmodel import select

            from app.database import OrderRecord

            rows = list(session.exec(select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(30)).all())
            orders = [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                }
                for r in rows
            ]
        except Exception:
            missing.append("orders")
        try:
            from app.services.portfolio_reconciliation_service import portfolio_reconciliation

            recon = portfolio_reconciliation(session, ConfigManager(session).get_current())
        except Exception:
            missing.append("reconciliation")

        open_btc = next((p for p in positions if "BTC" in str(p.get("symbol", ""))), None)
        next_action = None
        if open_btc:
            next_action = "Exit monitor active — do not open duplicate BTC entries"
        elif recon.get("broker_sync_rate_limited"):
            next_action = "Broker sync rate-limited — wait before new entries"

        return _envelope(
            {
                "positions": positions,
                "orders": orders,
                "reconciliation": recon,
                "broker_truth_authoritative": True,
                "local_orders_incomplete": len(orders) == 0 and len(positions) > 0,
                "open_btc": open_btc,
                "next_action": next_action or recon.get("plain") or "Review broker positions",
                "message": "Broker truth is authoritative. Local order history may be incomplete.",
            },
            missing_sections=missing,
        )

    return _cached_get("portfolio", build)


def page_state_performance(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        cfg = ConfigManager(session).get_current()
        summary: dict = {}
        curve: dict = {}
        try:
            from app.services.performance_service import equity_curve, performance_summary

            summary = performance_summary(session, cfg)
            curve = equity_curve(session)
        except Exception as exc:
            return _envelope({"error": str(exc)[:120]}, missing_sections=["performance"])
        return _envelope({"summary": summary, "equity_curve": curve})

    return _cached_get("performance", build)


def page_state_activity(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        try:
            from app.services.activity_feed_service import activity_feed, latest_tick_card

            feed = activity_feed(session, 30)
            tick = latest_tick_card(session)
            return _envelope({"feed": feed, "latest_tick_card": tick})
        except Exception as exc:
            return _envelope({"status": "degraded"}, warnings=[str(exc)[:120]], missing_sections=["activity"])

    return _cached_get("activity", build)


def page_state_reports(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        env = env_pause_status()
        job = __import__(
            "app.services.diagnostic_export_job_service",
            fromlist=["export_job_status"],
        ).export_job_status()
        readable = {
            "paper_trading": "Active",
            "autonomous_learning": "Active" if not env.get("paper_trading_paused_by_env") else "Paused by env",
            "scheduler": "Active",
            "environment_pause": "On" if env.get("any_env_pause") else "Off",
            "broker_sync": "See portfolio",
            "export_health": "running" if job.get("export_in_progress") else "ok",
        }
        return _envelope(
            {
                "readable_status": readable,
                "env_pause": env,
                "export_job": job,
                "technical_details": {"env_pause_raw": env},
            },
        )

    return _cached_get("reports", build)


_PARAM_LABELS = {
    "daily_loss_limit_pct": "Daily loss limit",
    "max_open_positions": "Maximum open positions",
    "cash_reserve_pct": "Cash reserve",
    "max_per_symbol_exposure_pct": "Max exposure per symbol",
    "stale_quote_limit_seconds": "Stale quote limit",
    "stale_bar_limit_minutes": "Stale bar limit",
    "reconciliation_drift_bps": "Reconciliation drift limit",
    "push_strength_min": "Minimum push strength",
    "min_edge_after_cost_bps": "Minimum edge after cost",
    "profit_target_bps": "Profit target",
    "atr_stop_multiplier": "ATR stop multiplier",
    "timeout_minutes": "Timeout",
}


def page_state_control_center(session: Session) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        try:
            from app.services.control_center_service import control_center_status

            raw = control_center_status(session)
            params = raw.get("strategy_parameters") or {}
            labeled = {_PARAM_LABELS.get(k, k.replace("_", " ").title()): v for k, v in params.items()}
            return _envelope({**raw, "strategy_parameters_labeled": labeled})
        except Exception as exc:
            return _envelope({"status": "degraded"}, warnings=[str(exc)[:120]])

    return _cached_get("control-center", build)


PAGE_BUILDERS: dict[str, Callable[[Session], dict[str, Any]]] = {
    "mission-control": page_state_mission_control,
    "universe": page_state_universe,
    "push-pull": page_state_push_pull,
    "ai-manager": page_state_ai_manager,
    "hive-mind": page_state_hive_mind,
    "portfolio": page_state_portfolio,
    "performance": page_state_performance,
    "activity": page_state_activity,
    "reports": page_state_reports,
    "control-center": page_state_control_center,
}


def get_page_state(session: Session, page: str) -> dict[str, Any]:
    fn = PAGE_BUILDERS.get(page)
    if not fn:
        return _envelope({"status": "error", "message": f"Unknown page: {page}"}, warnings=[f"no builder for {page}"])
    return fn(session)
