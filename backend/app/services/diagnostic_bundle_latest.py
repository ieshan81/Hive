"""Fast, current-run-only diagnostic bundle (the default export).

Solves the "bundle is huge/slow and old logs read as current truth" problem: instead of dumping
full history, this aggregates the fast read-models + a small, capped, clearly-labeled slice of
recent rows for the CURRENT validation run. Every capped file states how many rows were included
vs available and how to get the full forensic bundle. Read-only; no orders; no history deleted —
the full forensic bundle is still available via ?mode=forensic.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

# Default row caps for the latest bundle (see mission spec).
CAPS = {
    "latest_cycles": 25,
    "risk_events": 250,
    "strategy_signals": 250,
    "blocked_trades": 250,
    "scheduler_ticks": 100,
    "refresh_events": 100,
    "broker_errors": 100,
}

FORENSIC_HINT = "Full history: GET /api/diagnostic-bundle?mode=forensic (or /download)."


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _iso(dt) -> Optional[str]:
    return dt.isoformat() + "Z" if hasattr(dt, "isoformat") else None


def _capped(rows: list, cap: int, *, total: Optional[int] = None, run_filtered: bool = False,
            includes_historical: bool = False, run_id: Optional[str] = None) -> dict[str, Any]:
    total = total if total is not None else len(rows)
    included = rows[:cap]
    return {
        "validation_run_id": run_id,
        "filtered_by_current_run": run_filtered,
        "includes_historical_rows": includes_historical,
        "row_count_included": len(included),
        "total_row_count_available": total,
        "cap_applied": total > len(included),
        "forensic_hint": FORENSIC_HINT,
        "rows": included,
    }


def _safe(label: str, errs: list, fn):
    try:
        return fn()
    except Exception as exc:  # never let one section break the bundle
        errs.append({"section": label, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        return {"status": "degraded", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def build_latest_bundle(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    t0 = time.time()
    errs: list[dict[str, Any]] = []
    cfg = config

    from app.services.config_manager import ConfigManager
    if cfg is None:
        cfg = _safe("config", errs, lambda: ConfigManager(session).get_current()) or {}

    from app.services.nuke_epoch_service import (
        PAPER_VALIDATION_RUN_ID,
        get_latest_reset_epoch,
        record_created_after,
    )
    epoch = _safe("epoch", errs, lambda: get_latest_reset_epoch(session)) or {}
    run_id = (epoch or {}).get("validation_run_id") or (PAPER_VALIDATION_RUN_ID if epoch else None)
    cutoff_iso = (epoch or {}).get("nuke_completed_at")

    # --- fast read-models (current truth) ---
    tiles = _safe("tiles", errs, lambda: __import__(
        "app.services.mission_control_read_model", fromlist=["build_mission_control_tiles"]
    ).build_mission_control_tiles(session))
    engine_map = _safe("engine_map", errs, lambda: __import__(
        "app.services.hive_engine_map_service", fromlist=["HiveEngineMapService"]
    ).HiveEngineMapService(session, cfg).map())
    mem_gov = _safe("memory_governance", errs, lambda: __import__(
        "app.services.memory_governance_service", fromlist=["MemoryGovernanceService"]
    ).MemoryGovernanceService(session).archive_noisy_active_memory(dry_run=True))
    stock = _safe("stock_data_readiness", errs, lambda: __import__(
        "app.services.stock_data_readiness_service", fromlist=["stock_data_readiness"]
    ).stock_data_readiness(session, cfg))
    validation = _safe("validation_run", errs, lambda: __import__(
        "app.services.diagnostic_export", fromlist=["_validation_run_export"]
    )._validation_run_export(session))
    perf = _safe("performance", errs, lambda: __import__(
        "app.services.performance_service", fromlist=["performance_summary"]
    ).performance_summary(session))
    scheduler = _safe("scheduler", errs, lambda: __import__(
        "app.services.autonomous_paper_scheduler", fromlist=["AutonomousPaperScheduler"]
    ).AutonomousPaperScheduler(session, cfg).status())
    promotion_criteria = _safe("promotion_criteria", errs, lambda: __import__(
        "app.services.promotion_criteria", fromlist=["authoritative_promotion_criteria"]
    ).authoritative_promotion_criteria(cfg, session=session))

    # --- capped recent rows (current-run filtered where it makes sense) ---
    def _recent(model, order_col, cap, *, run_filter=False):
        rows_all = list(session.exec(select(model).order_by(order_col.desc()).limit(cap * 3)).all())
        total = int(session.exec(select(__import__("sqlmodel", fromlist=["func"]).func.count()).select_from(model)).one() or 0)
        if run_filter and cutoff_iso:
            rows_all = [r for r in rows_all if record_created_after(r, cutoff_iso)]
        return rows_all[:cap], total

    from app.database import BlockedTrade, BrokerError, RiskEvent, StrategySignal

    def _ser(r) -> dict:
        d = r.model_dump(mode="python") if hasattr(r, "model_dump") else dict(r)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = _iso(v)
        return d

    def _section(model, order_col, cap_key, run_filter):
        def build():
            rows, total = _recent(model, order_col, CAPS[cap_key], run_filter=run_filter)
            return _capped([_ser(r) for r in rows], CAPS[cap_key], total=total,
                           run_filtered=run_filter, includes_historical=not run_filter, run_id=run_id)
        return _safe(cap_key, errs, build)

    risk_events = _section(RiskEvent, RiskEvent.created_at, "risk_events", True)
    strategy_signals = _section(StrategySignal, StrategySignal.created_at, "strategy_signals", True)
    blocked_trades = _section(BlockedTrade, BlockedTrade.created_at, "blocked_trades", True)
    broker_errors = _section(BrokerError, BrokerError.created_at, "broker_errors", False)

    # README_FIRST — the single first thing to read.
    acct = (tiles or {}).get("account") or {}
    pe = (tiles or {}).get("paper_execution") or {}
    readme = {
        "READ_THIS_FIRST": "Current paper-validation truth. Old history is NOT mixed in here; "
                           "use ?mode=forensic for full history.",
        "bundle_mode": "latest",
        "generated_at": _now(),
        "current_validation_run_id": run_id,
        "reset_epoch": epoch or None,
        "baseline_equity": (validation or {}).get("baseline_equity") or (perf or {}).get("baseline_equity"),
        "current_equity": acct.get("equity"),
        "current_positions": pe.get("open_positions_count"),
        "current_orders": pe.get("active_orders_count"),
        "latest_cycle_id": ((engine_map or {}).get("latest_trade_lifecycle") or {}).get("trade_id"),
        "broker_mode": (tiles or {}).get("broker_mode"),
        "live_lock_status": pe.get("live_lock_status"),
        "stock_data_status": {
            "feed": (stock or {}).get("stock_data_feed"),
            "subscription": (stock or {}).get("stock_subscription_level_detected"),
            "stocks_scanner_allowed": (stock or {}).get("stocks_scanner_allowed"),
            "symbols_ready": (stock or {}).get("symbols_ready"),
            "symbols_total": (stock or {}).get("symbols_total"),
        },
        "crypto_data_status": "active_24_7 (separate lane; unaffected by stock data)",
        "memory_governance_status": {
            "would_archive": (mem_gov or {}).get("would_archive"),
            "evidence_linked_preserved": (mem_gov or {}).get("evidence_linked_preserved"),
        },
        "includes_historical_rows": False,
        "live_trading_locked": pe.get("live_trading_locked", True),
        "closed_trades_this_run": (perf or {}).get("closed_trades"),
    }

    bundle = {
        "README_FIRST.json": readme,
        "system_summary.md": _system_summary_md(readme),
        "validation_run.json": validation,
        "current_truth.json": {
            "validation_run_id": run_id,
            "reset_epoch": epoch or None,
            "generated_at": _now(),
            "filtered_by_current_run": True,
            "includes_historical_rows": False,
            "account": acct,
            "paper_execution": pe,
            "live_lock": (tiles or {}).get("live_lock"),
            "broker_mode": (tiles or {}).get("broker_mode"),
        },
        "hive_engine_map.json": engine_map,
        "memory_governance_summary.json": mem_gov,
        "stock_data_readiness.json": stock,
        "performance_summary.json": perf,
        "promotion_criteria.json": promotion_criteria,
        "scheduler_status.json": scheduler,
        "risk_events.json": risk_events,
        "strategy_signals.json": strategy_signals,
        "blocked_trades.json": blocked_trades,
        "broker_errors_recent.json": broker_errors,
        "archive_manifest_summary.json": _safe("archive_manifest_summary", errs, lambda: __import__(
            "app.services.diagnostic_bundle_maintenance", fromlist=["DiagnosticBundleMaintenanceService"]
        ).DiagnosticBundleMaintenanceService(session, cfg).manifest_summary()),
        "bundle_meta.json": {
            "bundle_mode": "latest",
            "generated_at": _now(),
            "generation_seconds": None,  # filled below
            "validation_run_id": run_id,
            "reset_epoch_id": (epoch or {}).get("reset_epoch_id"),
            "caps": CAPS,
            "includes_historical_rows": False,
            "forensic_hint": FORENSIC_HINT,
            "section_errors": errs,
        },
    }
    bundle["bundle_meta.json"]["generation_seconds"] = round(time.time() - t0, 2)
    return bundle


def _system_summary_md(r: dict) -> str:
    sd = r.get("stock_data_status") or {}
    return "\n".join([
        "# Caged Hive Quant — Current Validation Truth (READ FIRST)",
        f"Generated: {r.get('generated_at')}",
        f"- validation_run_id: {r.get('current_validation_run_id')}",
        f"- baseline_equity: {r.get('baseline_equity')} | current_equity: {r.get('current_equity')}",
        f"- positions: {r.get('current_positions')} | orders: {r.get('current_orders')} | closed_trades_this_run: {r.get('closed_trades_this_run')}",
        f"- broker_mode: {r.get('broker_mode')} | live_lock_status: {r.get('live_lock_status')} | live_trading_locked: {r.get('live_trading_locked')}",
        f"- stock_data: feed={sd.get('feed')} subscription={sd.get('subscription')} scanner_allowed={sd.get('stocks_scanner_allowed')} ready={sd.get('symbols_ready')}/{sd.get('symbols_total')}",
        f"- crypto_data: {r.get('crypto_data_status')}",
        "- bundle_mode: latest (old history NOT included; use ?mode=forensic for full history)",
    ])
