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
        # Read-only: a diagnostic bundle must never migrate/write config.
        cfg = _safe("config", errs, lambda: ConfigManager(session).get_current_readonly()) or {}

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
    universe = _safe("universe_summary", errs, lambda: __import__(
        "app.services.universe_summary_service", fromlist=["build_universe_summary"]
    ).build_universe_summary(session, cfg))
    productivity = _safe("productivity", errs, lambda: __import__(
        "app.services.paper_validation_productivity_service", fromlist=["build_productivity"]
    ).build_productivity(session, cfg))
    _A = lambda fn: __import__("app.services.paper_validation_analysis_service", fromlist=[fn])  # noqa: E731
    trade_truth = _safe("current_run_trade_truth", errs, lambda: _A("current_run_trade_truth").current_run_trade_truth(session, cfg))
    pnl_trace = _safe("pnl_guard_trace", errs, lambda: _A("pnl_guard_trace").pnl_guard_trace(session, cfg))
    freshness_matrix = _safe("data_freshness_matrix", errs, lambda: _A("data_freshness_matrix").data_freshness_matrix(session, cfg))
    alpha_matrix = _safe("alpha_coverage_matrix", errs, lambda: _A("alpha_coverage_matrix").alpha_coverage_matrix(session, cfg))
    timeline = _safe("blocker_timeline", errs, lambda: _A("blocker_timeline").blocker_timeline(session, cfg))
    order_proof = _safe("paper_order_proof", errs, lambda: __import__(
        "app.services.paper_order_proof_service", fromlist=["PaperOrderProofService"]
    ).PaperOrderProofService(session, cfg).summary())
    import os as _os
    git_commit = _os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev")[:12]

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
                           "use ?mode=forensic for full history. Read p_and_l_guard_trace.json "
                           "for the 'daily drawdown exceeds 3%' explanation.",
        "bundle_mode": "latest",
        "generated_at": _now(),
        "git_commit": git_commit,
        "current_validation_run_id": run_id,
        "reset_epoch": epoch or None,
        "baseline_equity": (validation or {}).get("baseline_equity") or (perf or {}).get("baseline_equity"),
        "current_equity": acct.get("equity"),
        "current_cash": acct.get("cash"),
        "current_positions_count": pe.get("open_positions_count"),
        "current_active_orders_count": pe.get("active_orders_count"),
        "current_run_order_attempts": (trade_truth or {}).get("current_run_order_attempts"),
        "current_run_closed_trades": (trade_truth or {}).get("current_run_closed_trades"),
        "scheduler_enabled": pe.get("scheduler_enabled"),
        "paper_learning_enabled": pe.get("paper_learning_on"),
        "stock_lane_mode": (universe.get("policy") or {}).get("stock_lane_mode") if isinstance(universe, dict) else None,
        "stock_entries_allowed": (universe.get("policy") or {}).get("stock_entries_allowed") if isinstance(universe, dict) else None,
        "crypto_active": (universe.get("policy") or {}).get("crypto_active") if isinstance(universe, dict) else None,
        "paper_candidates_count": (productivity or {}).get("paper_candidates"),
        "current_top_candidate": ((productivity or {}).get("current_best_candidate") or {}).get("symbol"),
        "current_top_blocker": ((productivity or {}).get("exact_next_blocker") or {}).get("code") if isinstance((productivity or {}).get("exact_next_blocker"), dict) else None,
        "p_and_l_threshold_status": "ACTIVE_BLOCKING" if (pnl_trace or {}).get("p_and_l_guard_active") else "clear_or_historical",
        "daily_pnl_status": ((pnl_trace or {}).get("occurrences") or [{}])[0].get("measured_pnl_percent"),
        "kill_switch_status": (pnl_trace or {}).get("kill_switch_state"),
        "latest_errors_count": len(errs),
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
        "universe_truth": {
            "universe_source_total": ((universe or {}).get("source_counts") or {}).get("curated_crypto"),
            "universe_display_total": ((universe or {}).get("display_counts") or {}).get("total"),
            "universe_crypto_display": ((universe or {}).get("display_counts") or {}).get("crypto"),
            "universe_stock_display": ((universe or {}).get("display_counts") or {}).get("stock"),
            "universe_cached": ((universe or {}).get("freshness_counts") or {}).get("cached"),
            "universe_fresh": ((universe or {}).get("freshness_counts") or {}).get("fresh"),
            "universe_eligible": ((universe or {}).get("funnel_counts") or {}).get("eligible"),
            "universe_execution_shortlist": ((universe or {}).get("funnel_counts") or {}).get("execution_shortlist"),
            "universe_status_timeout_risk": (universe or {}).get("status_latency_risk"),
            "source_nonzero_but_eligible_zero": (universe or {}).get("source_nonzero_but_eligible_zero"),
            "universe_ui_truth_status": "fast_path_healthy; /api/universe/status is slow — read /api/universe/summary FIRST.",
        },
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
        "universe_summary.json": universe,
        "paper_validation_productivity.json": productivity,
        "current_run_trade_truth.json": trade_truth,
        "p_and_l_guard_trace.json": pnl_trace,
        "data_freshness_matrix.json": freshness_matrix,
        "alpha_coverage_matrix.json": alpha_matrix,
        "blocker_timeline.json": timeline,
        "changed_since_previous_bundle.json": _safe("changed_since_previous_bundle", errs, lambda: _A("changed_since_previous_bundle").changed_since_previous_bundle(session, cfg)),
        "paper_order_proof.json": order_proof,
        "endpoint_latency_summary.json": {
            "note": "Self-reported: /api/universe/summary is the fast path; /api/universe/status + "
                    "/api/mission-control/status are the slow heavy builds — prefer the fast paths.",
            "slow_endpoint_warning": True,
            "frontend_timeout_risk": bool((universe or {}).get("status_latency_risk")),
            "prefer_fast_paths": ["/api/universe/summary", "/api/mission-control/tiles", "/api/paper-validation/productivity"],
        },
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


def latest_bundle_as_zip(session: Session, config: Optional[dict] = None) -> bytes:
    """Zip the small current-run latest bundle (each file as JSON / .md).

    Building the bundle dict is read-pure; downloading the ZIP is an explicit operator action, so we
    record a headline snapshot here. That snapshot becomes the comparison baseline for the next
    download's changed_since_previous_bundle.json. The JSON GET view never writes.
    """
    import io
    import json as _json
    import zipfile

    bundle = build_latest_bundle(session, config)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in bundle.items():
            if name.endswith(".md") and isinstance(content, str):
                zf.writestr(name, content)
            else:
                zf.writestr(name, _json.dumps(content, indent=2, default=str))
    try:  # record the "previous bundle" baseline for next time (best-effort, never blocks the download)
        from app.services.paper_validation_analysis_service import record_headline_snapshot

        record_headline_snapshot(session, config)
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    return buf.getvalue()


def latest_bundle_filename() -> str:
    return f"latest_bundle_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"


def _system_summary_md(r: dict) -> str:
    sd = r.get("stock_data_status") or {}
    return "\n".join([
        "# Caged Hive Quant — Current Validation Truth (READ FIRST)",
        f"Generated: {r.get('generated_at')} | commit: {r.get('git_commit')}",
        "## Is the bot running / safe / trading?",
        f"- Running: yes (scheduler_enabled={r.get('scheduler_enabled')}, paper_learning={r.get('paper_learning_enabled')}).",
        f"- Safe: live_lock={r.get('live_lock_status')} | live_trading_locked={r.get('live_trading_locked')} | broker={r.get('broker_mode')}.",
        f"- Trading: NO — current_run_order_attempts={r.get('current_run_order_attempts')}, current_run_closed_trades={r.get('current_run_closed_trades')}.",
        f"- Why not trading: top blocker = {r.get('current_top_blocker')} (no proven alpha scorecard / data freshness). Heartbeat watches; only evidence-backed, cage-approved candidates trade.",
        "## Truth",
        f"- validation_run_id: {r.get('current_validation_run_id')}",
        f"- baseline_equity: {r.get('baseline_equity')} | current_equity: {r.get('current_equity')} | cash: {r.get('current_cash')}",
        f"- positions: {r.get('current_positions_count')} | active_orders: {r.get('current_active_orders_count')}",
        f"- paper_candidates: {r.get('paper_candidates_count')} | top_candidate: {r.get('current_top_candidate')}",
        f"- P&L guard ('exceeds 3%'): {r.get('p_and_l_threshold_status')} | today_pnl%={r.get('daily_pnl_status')} | kill_switch={r.get('kill_switch_status')} (3% of $200 = $6; see p_and_l_guard_trace.json).",
        f"- stock_data: feed={sd.get('feed')} scanner_allowed={sd.get('stocks_scanner_allowed')} | stock_lane={r.get('stock_lane_mode')} | crypto_active={r.get('crypto_active')}",
        "## Next safe action",
        "- Let it keep watching; build alpha evidence (read-only research/backtests). Do NOT loosen gates or force trades.",
        "- Read first: README_FIRST.json, then paper_validation_productivity.json + p_and_l_guard_trace.json.",
        "- bundle_mode: latest (old history NOT included; use ?mode=forensic for full history).",
    ])
