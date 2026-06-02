"""Analysis-first read models for the latest diagnostic bundle (ChatGPT/Claude-friendly).

All read-only. Separates CURRENT-RUN truth (post reset_epoch) from HISTORICAL rows so old orders/
trades can never be mistaken for paper_validation_run_001. Includes a P&L-guard trace that explains
the "daily drawdown exceeds 3%" kill-switch in plain English (3% of $200 = $6) and whether it is
current/historical and blocking. Never trades, never mutates, never enables live.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, func, select


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt) -> Optional[str]:
    return dt.isoformat() + "Z" if hasattr(dt, "isoformat") else None


def _epoch(session: Session) -> dict:
    try:
        from app.services.nuke_epoch_service import get_latest_reset_epoch

        return get_latest_reset_epoch(session) or {}
    except Exception:
        return {}


def _cutoff(epoch: dict) -> Optional[datetime]:
    c = (epoch or {}).get("nuke_completed_at")
    if not c:
        return None
    try:
        return datetime.fromisoformat(str(c).replace("Z", "").split("+")[0])
    except ValueError:
        return None


def _count(session: Session, model, *where) -> int:
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    try:
        return int(session.exec(q).one() or 0)
    except Exception:
        return 0


def current_run_trade_truth(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Current-run order attempts / trades vs historical, never conflated."""
    from app.database import ExecutionLog, OrderRecord, PaperExperimentOutcome, PositionSnapshot, TradeRecord

    epoch = _epoch(session)
    run_id = epoch.get("validation_run_id") or "paper_validation_run_001"
    cut = _cutoff(epoch)

    SUBMITTED = ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled")
    FILLED = ("paper_order_filled", "paper_order_partially_filled")

    def _cur(model, *extra, ts: str = "created_at"):
        where = list(extra)
        col = getattr(model, ts, None)
        if cut is not None and col is not None:
            where.append(col >= cut)
        return _count(session, model, *where)

    attempts = _cur(ExecutionLog) if cut is not None else 0
    submitted = _cur(ExecutionLog, ExecutionLog.status.in_(SUBMITTED)) if cut is not None else 0
    filled = _cur(ExecutionLog, ExecutionLog.status.in_(FILLED)) if cut is not None else 0
    open_positions = _count(session, PositionSnapshot, PositionSnapshot.qty > 0)
    # TradeRecord has no created_at — a closed trade belongs to the current run by its closed_at.
    closed = _cur(TradeRecord, TradeRecord.status == "closed", ts="closed_at") if cut is not None else 0

    realized = 0.0
    try:
        rows = session.exec(select(TradeRecord).where(TradeRecord.status == "closed")).all()
        realized = round(sum(float(getattr(t, "pl_dollars", 0) or 0) for t in rows if cut is None or (getattr(t, "closed_at", None) or getattr(t, "created_at", None) or _now()) >= cut), 4)
    except Exception:
        realized = 0.0

    return {
        "validation_run_id": run_id,
        "reset_epoch": epoch or None,
        "current_run_order_attempts": attempts,
        "current_run_submitted_orders": submitted,
        "current_run_filled_orders": filled,
        "current_run_open_positions": open_positions,
        "current_run_closed_trades": closed,
        "current_run_realized_pnl": realized,
        "current_run_unrealized_pnl": 0.0,
        "current_run_pnl_percent": round(realized / 200.0 * 100, 3) if realized else 0.0,
        "current_run_max_drawdown_percent": 0.0,
        "historical_orders_count": _count(session, OrderRecord),
        "historical_trades_count": _count(session, TradeRecord),
        "historical_outcomes_count": _count(session, PaperExperimentOutcome),
        "historical_rows_excluded_from_latest": True,
        "note": "current_run_* are post-reset_epoch; historical_* are all-time and are NOT current-run truth.",
    }


def pnl_guard_trace(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Trace the daily-drawdown / P&L kill-switch ('exceeds 3%') — source, value, current vs historical."""
    from app.services.config_manager import ConfigManager
    from app.services.engine_config import cfg_get

    cfg = config if config is not None else (ConfigManager(session).get_current_readonly() if True else {})
    daily_lim = float(cfg_get(cfg, "kill.daily_drawdown_pct", 2.0))
    max_dd = float(cfg_get(cfg, "kill.max_drawdown_pct", 12.0))
    baseline = 200.0

    ks = {}
    try:
        ks = __import__("app.services.kill_switch_service", fromlist=["KillSwitchService"]).KillSwitchService(session, cfg).status()
    except Exception:
        ks = {}
    daily_pl_pct = ks.get("account_daily_pl_pct")
    drawdown_pct = ks.get("account_drawdown_pct")
    entries_allowed = ks.get("entries_allowed", True)
    last_block = ks.get("last_preflight_block") or {}
    epoch = _epoch(session)
    cut = _cutoff(epoch)

    block_at = last_block.get("created_at")
    is_current = False
    if block_at and cut is not None:
        try:
            is_current = datetime.fromisoformat(str(block_at).replace("Z", "").split("+")[0]) >= cut
        except ValueError:
            is_current = False

    active = (entries_allowed is False)
    dollars = round(baseline * daily_lim / 100.0, 2)
    plain = (
        f"The '3%' is the daily-drawdown kill-switch threshold (kill.daily_drawdown_pct = {daily_lim}%). "
        f"On the ${baseline:.0f} baseline, {daily_lim}% = ${dollars:.2f}. "
    )
    if active:
        plain += "It is CURRENTLY ACTIVE and blocking new entries."
    elif last_block and not is_current:
        plain += ("The only trip is HISTORICAL (a previous block); the kill-switch is currently CLEARED "
                  f"(today's P/L {daily_pl_pct}%), so it is NOT blocking now.")
    else:
        plain += f"It is NOT active now (today's P/L {daily_pl_pct}%, drawdown {drawdown_pct}%)."

    return {
        "occurrences": [
            {
                "source_file": "app/services/kill_switch_service.py",
                "source_service": "KillSwitchService.evaluate",
                "source_endpoint": "/api/execution/paper/status (kill_switch)",
                "database_table": "AccountSnapshot (daily_pl_pct/drawdown_pct), KillSwitchEvent",
                "validation_run_id": (epoch or {}).get("validation_run_id"),
                "reset_epoch": (epoch or {}).get("reset_epoch_id"),
                "threshold_type": "daily_drawdown",
                "threshold_value": daily_lim,
                "threshold_unit": "percent",
                "measured_pnl_percent": daily_pl_pct,
                "account_equity_used": ks.get("account_equity"),
                "baseline_equity_used": baseline,
                "is_current_run": is_current,
                "is_historical": bool(last_block) and not is_current,
                "did_it_block_entries": active,
                "did_it_trigger_kill_switch": active,
                "is_still_active": active,
                "last_block": last_block or None,
                "explanation_plain_english": plain,
            }
        ],
        "max_drawdown_threshold_pct": max_dd,
        "kill_switch_state": ks.get("state"),
        "entries_allowed_now": entries_allowed,
        "p_and_l_guard_active": active,
        "summary": plain,
    }


def data_freshness_matrix(session: Session, config: Optional[dict] = None, *, max_symbols: int = 40) -> dict[str, Any]:
    """Per-symbol latest bar age + freshness (crypto from DB bars; stock from the readiness probe)."""
    from app.database import HistoricalBar
    from app.services.engine_config import cfg_get

    cfg = config or {}
    now = _now()
    max_age_h = float(cfg_get(cfg, "universe.max_bar_staleness_hours", 96))
    rows: list[dict[str, Any]] = []
    try:
        syms = [r[0] for r in session.exec(
            select(HistoricalBar.symbol, func.max(HistoricalBar.timestamp))
            .group_by(HistoricalBar.symbol).limit(max_symbols)
        ).all()]
    except Exception:
        syms = []
    for sym in syms[:max_symbols]:
        try:
            last = session.exec(
                select(HistoricalBar).where(HistoricalBar.symbol == sym).order_by(HistoricalBar.timestamp.desc()).limit(1)
            ).first()
        except Exception:
            last = None
        if not last:
            continue
        age_min = round((now - last.timestamp).total_seconds() / 60.0, 1) if last.timestamp else None
        fresh = age_min is not None and age_min <= max_age_h * 60
        rows.append({
            "symbol": sym,
            "asset_class": getattr(last, "asset_class", None) or ("crypto" if "/" in sym else "stock"),
            "timeframe": getattr(last, "timeframe", None),
            "latest_bar_time": _iso(last.timestamp),
            "server_time": _iso(now),
            "bar_age_minutes": age_min,
            "freshness_threshold_minutes": round(max_age_h * 60, 1),
            "freshness_status": "fresh" if fresh else "stale",
            "trade_allowed": bool(fresh),
            "source": "HistoricalBar (DB)",
        })
    return {
        "generated_at": _iso(now),
        "freshness_threshold_minutes": round(max_age_h * 60, 1),
        "symbols": rows,
        "fresh_count": sum(1 for r in rows if r["freshness_status"] == "fresh"),
        "stale_count": sum(1 for r in rows if r["freshness_status"] == "stale"),
        "note": "One threshold policy (universe.max_bar_staleness_hours). A stale bar is never trade_allowed.",
    }


def alpha_coverage_matrix(session: Session, config: Optional[dict] = None, *, max_symbols: int = 60) -> dict[str, Any]:
    """Per scanned crypto symbol: alpha scorecard state (no_scorecard / unproven / rejected / paper_candidate)."""
    from app.database import AlphaScorecard, SymbolCandidate

    def _norm(s: str) -> str:
        return str(s or "").upper().replace("/", "")

    cards: dict[str, Any] = {}
    try:
        for sc in session.exec(select(AlphaScorecard)).all():
            cards.setdefault(_norm(sc.symbol), sc)
    except Exception:
        cards = {}
    try:
        scanned = [c.symbol for c in session.exec(select(SymbolCandidate).limit(max_symbols)).all()]
    except Exception:
        scanned = []
    scanned = [s for s in dict.fromkeys(scanned) if "/" in str(s)][:max_symbols]

    rows = []
    PAPER_OK = ("paper_candidate", "proven")
    for sym in scanned:
        sc = cards.get(_norm(sym))
        if sc is None:
            rows.append({"symbol": sym, "has_scorecard": False, "scorecard_stage": "no_scorecard",
                         "blocker": "NO_ALPHA_SCORECARD", "next_evidence_needed": "Run research/backtest to create a scorecard."})
            continue
        verdict = str(sc.verdict or "")
        rows.append({
            "symbol": sym,
            "has_scorecard": True,
            "scorecard_stage": getattr(sc, "current_stage", None) or verdict,
            "verdict": verdict,
            "sample_size": getattr(sc, "sample_size", None),
            "expectancy": getattr(sc, "expectancy", None),
            "edge_after_cost_bps": getattr(sc, "edge_after_cost_bps", None),
            "profit_factor": getattr(sc, "profit_factor", None),
            "blocker": None if verdict in PAPER_OK else ("REJECTED" if verdict == "rejected" else "UNPROVEN_INSUFFICIENT_EVIDENCE"),
            "next_evidence_needed": None if verdict in PAPER_OK else "More closed-trade / backtest evidence to qualify.",
        })
    return {
        "generated_at": _iso(_now()),
        "scanned_symbols": len(scanned),
        "with_scorecard": sum(1 for r in rows if r["has_scorecard"]),
        "no_scorecard": sum(1 for r in rows if not r["has_scorecard"]),
        "paper_candidates": sum(1 for r in rows if r.get("verdict") in PAPER_OK),
        "symbols": rows,
        "note": "Symbol normalization (ETHUSD == ETH/USD) prevents a format mismatch from hiding a scorecard. "
                "No symbol is promoted without deterministic criteria.",
    }


def blocker_timeline(session: Session, config: Optional[dict] = None, *, limit: int = 100) -> dict[str, Any]:
    """Recent current-run blockers (capped), grouped by code + phase."""
    from app.database import ExecutionLog

    epoch = _epoch(session)
    cut = _cutoff(epoch)
    rows: list[dict[str, Any]] = []
    try:
        q = select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(limit * 2)
        for r in session.exec(q).all():
            if r.reject_reason and (cut is None or (r.created_at and r.created_at >= cut)):
                rows.append({"code": r.reject_reason, "symbol": r.symbol, "at": _iso(r.created_at),
                             "current_run": cut is not None and bool(r.created_at and r.created_at >= cut)})
    except Exception:
        rows = []
    from collections import Counter
    grouped = Counter(r["code"] for r in rows)
    return {
        "generated_at": _iso(_now()),
        "validation_run_id": (epoch or {}).get("validation_run_id"),
        "recent_blockers": rows[:limit],
        "grouped_by_code": dict(grouped.most_common(20)),
        "note": "Current-run blockers only (post reset_epoch), capped.",
    }


# --- changed-since-previous-bundle (delta vs the last downloaded bundle) ---------------------
HEADLINE_SNAPSHOT_ACTION = "diagnostic_headline_snapshot"

# Numeric headline fields that get a signed delta in the change report.
_HEADLINE_NUMERIC = (
    "current_run_order_attempts", "current_run_submitted_orders", "current_run_filled_orders",
    "current_run_closed_trades", "current_run_realized_pnl", "current_run_open_positions",
    "paper_candidates_count", "stale_count", "fresh_count", "no_scorecard_count",
)


def _current_headline(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Small, read-only set of current-run headline metrics used for bundle-to-bundle deltas."""
    tt = current_run_trade_truth(session, config)
    fm = data_freshness_matrix(session, config)
    am = alpha_coverage_matrix(session, config)
    pnl = pnl_guard_trace(session, config)
    try:
        from app.services.paper_validation_productivity_service import build_productivity

        prod = build_productivity(session, config) or {}
    except Exception:
        prod = {}
    return {
        "validation_run_id": tt.get("validation_run_id"),
        "snapshot_at": _iso(_now()),
        "current_run_order_attempts": tt.get("current_run_order_attempts"),
        "current_run_submitted_orders": tt.get("current_run_submitted_orders"),
        "current_run_filled_orders": tt.get("current_run_filled_orders"),
        "current_run_closed_trades": tt.get("current_run_closed_trades"),
        "current_run_realized_pnl": tt.get("current_run_realized_pnl"),
        "current_run_open_positions": tt.get("current_run_open_positions"),
        "paper_candidates_count": prod.get("paper_candidates"),
        "top_blocker": prod.get("exact_next_blocker") or prod.get("zero_candidate_reason"),
        "engine_state": prod.get("engine_state"),
        "fresh_count": fm.get("fresh_count"),
        "stale_count": fm.get("stale_count"),
        "no_scorecard_count": am.get("no_scorecard"),
        "p_and_l_guard_active": pnl.get("p_and_l_guard_active"),
    }


def record_headline_snapshot(session: Session, config: Optional[dict] = None,
                             headline: Optional[dict] = None) -> dict[str, Any]:
    """Persist the current headline (call ONLY from mutating download paths, not the read-pure build)."""
    from app.database import SettingsActionAudit

    h = headline or _current_headline(session, config)
    try:
        session.add(SettingsActionAudit(
            action=HEADLINE_SNAPSHOT_ACTION, actor="diagnostic_bundle", broker_mode="paper",
            paper_broker=True, live_trading_locked=True, live_orders_enabled=False, details_json=h,
        ))
        session.flush()
    except Exception:
        pass
    return h


def _last_headline_snapshot(session: Session) -> Optional[dict]:
    from app.database import SettingsActionAudit

    try:
        row = session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == HEADLINE_SNAPSHOT_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
        ).first()
        return dict(row.details_json or {}) if row else None
    except Exception:
        return None


def changed_since_previous_bundle(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """Read-only delta of headline metrics vs the last time a bundle ZIP was downloaded."""
    from app.database import DiagnosticExportJob

    prev = _last_headline_snapshot(session)
    cur = _current_headline(session, config)

    prev_job = None
    try:
        prev_job = session.exec(
            select(DiagnosticExportJob)
            .where(DiagnosticExportJob.status == "complete")
            .order_by(DiagnosticExportJob.completed_at.desc())
        ).first()
    except Exception:
        prev_job = None

    changes: dict[str, Any] = {}
    if prev:
        for k in _HEADLINE_NUMERIC:
            a, b = prev.get(k), cur.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
                changes[k] = {"previous": a, "current": b, "delta": round(b - a, 4)}
        for k in ("top_blocker", "engine_state", "p_and_l_guard_active"):
            if prev.get(k) != cur.get(k):
                changes[k] = {"previous": prev.get(k), "current": cur.get(k)}

    return {
        "generated_at": _iso(_now()),
        "previous_snapshot_available": prev is not None,
        "previous_snapshot_at": (prev or {}).get("snapshot_at"),
        "previous_export_at": _iso(getattr(prev_job, "completed_at", None)) if prev_job else None,
        "previous_export_file_count": getattr(prev_job, "file_count", None) if prev_job else None,
        "previous_export_zip_size_bytes": getattr(prev_job, "zip_size_bytes", None) if prev_job else None,
        "current_headline": cur,
        "changes": changes,
        "changed_fields_count": len(changes),
        "note": ("Deltas vs the last time a bundle ZIP was downloaded. If previous_snapshot_available is "
                 "false this is the baseline; the next ZIP download sets the comparison point. "
                 "The read-only JSON view never writes a snapshot."),
    }
