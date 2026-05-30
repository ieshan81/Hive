"""Paper Autopilot Operations Brain — self-heal missing exit plans.

Deterministic remediation inside the cage: recover plans from signals/logs or
attach a conservative emergency paper-only plan. Never places orders directly;
exit sells still route through TrainingExecutionService → ExecutionCage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, SettingsActionAudit, StrategySignal
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.dynamic_exit_levels_service import compute_dynamic_exit_levels
from app.services.engine_config import cfg_get
from app.services.exit_monitor_service import (
    _entry_context_for_symbol,
    _f,
    _pos_qty,
    _pos_symbol,
    open_positions_missing_exit_plan,
    resolve_exit_plan,
)
from app.services.historical_data_service import HistoricalDataService
from app.services.lesson_memory_service import LessonMemoryService
from app.services.paper_autopilot_caps import LIVE_OR_FILLED_STATUSES
from app.services.position_state_service import build_enriched_state, _persist_state
from app.services.symbol_normalize import display_symbol, symbols_match

SELF_HEAL_ACTION = "exit_plan_self_heal"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _apl_cfg(config: dict) -> dict:
    return dict(config.get("autonomous_paper_learning") or {})


def self_heal_enabled(config: dict) -> bool:
    return bool(_apl_cfg(config).get("auto_heal_missing_exit_plans", True))


def _documented_from_plan(plan: dict[str, Any]) -> bool:
    return bool(
        plan.get("stop_loss") is not None
        or plan.get("take_profit") is not None
        or plan.get("trailing_stop") is not None
        or plan.get("invalidation_price") is not None
        or plan.get("max_hold_hours") is not None
        or plan.get("expected_hold_time")
        or plan.get("exit_strategy")
    )


def _extract_recoverable_plan(sig: Optional[StrategySignal], meta: dict) -> dict[str, Any]:
    levels = meta.get("dynamic_exit_levels") if isinstance(meta.get("dynamic_exit_levels"), dict) else {}
    stop_loss = (_f(getattr(sig, "stop_loss", None)) if sig else None) or _f(levels.get("stop_loss"))
    take_profit = (_f(getattr(sig, "take_profit", None)) if sig else None) or _f(levels.get("take_profit"))
    trailing = _f(levels.get("trailing_stop")) or _f(meta.get("trailing_stop"))
    invalidation = _f(levels.get("invalidation_price")) or _f(meta.get("invalidation_price"))
    max_hold_hours = _f(meta.get("max_hold_hours")) or _f(meta.get("expected_hold_hours"))
    expected_hold_time = meta.get("expected_hold_time")
    exit_strategy = meta.get("exit_strategy")
    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trailing_stop": trailing,
        "invalidation_price": invalidation,
        "max_hold_hours": max_hold_hours,
        "expected_hold_time": expected_hold_time,
        "exit_strategy": exit_strategy,
        "dynamic_exit_levels": levels if levels else None,
    }


def _bars_for_symbol(session: Session, config: dict, symbol: str, asset_class: str) -> list[dict[str, Any]]:
    hist = HistoricalDataService(session, config)
    hist_symbol = display_symbol(symbol) if asset_class == "crypto" else symbol
    for timeframe, lookback_days in (("1Min", 2), ("5Min", 7)):
        try:
            bars, _meta = hist.get_bars(
                hist_symbol,
                timeframe=timeframe,
                min_rows=15,
                lookback_days=lookback_days,
                max_staleness_hours=2.0,
                asset_class=asset_class,
            )
        except Exception:
            bars = []
        if bars:
            return bars
    return []


def _compute_emergency_plan(
    session: Session,
    config: dict,
    *,
    symbol: str,
    entry_price: float,
    current_price: float,
    signal_meta: Optional[dict] = None,
) -> dict[str, Any]:
    apl = _apl_cfg(config)
    asset_class = "crypto" if "/" in display_symbol(symbol) or "USD" in symbol.upper() else "stock"
    quote_sym = normalize_crypto_symbol(symbol) if asset_class == "crypto" else symbol
    quote = {"mid": current_price or entry_price, "spread_pct": (signal_meta or {}).get("spread_pct")}
    bars = _bars_for_symbol(session, config, symbol, asset_class)
    levels_dict: Optional[dict[str, Any]] = None
    try:
        levels = compute_dynamic_exit_levels(
            config,
            symbol=display_symbol(symbol) if asset_class == "crypto" else symbol,
            side="buy",
            entry_price=entry_price,
            current_price=current_price or entry_price,
            bars=bars,
            quote=quote,
            signal_meta=signal_meta or {},
        )
        levels_dict = levels.to_dict()
    except Exception:
        levels_dict = None

    max_hold_h = float(apl.get("emergency_max_hold_hours", 24) or 24)
    if levels_dict and _documented_from_plan(levels_dict):
        return {
            "stop_loss": _f(levels_dict.get("stop_loss")),
            "take_profit": _f(levels_dict.get("take_profit")),
            "trailing_stop": _f(levels_dict.get("trailing_stop")),
            "invalidation_price": _f(levels_dict.get("invalidation_price")),
            "max_hold_hours": max_hold_h,
            "expected_hold_time": f"{max_hold_h}h",
            "exit_strategy": "emergency_dynamic_backfill",
            "dynamic_exit_levels": levels_dict,
        }

    loss_pct = float(apl.get("max_unrealized_loss_pct", 1.5) or 1.5)
    stop = round(entry_price * (1.0 - loss_pct / 100.0), 8)
    target = round(entry_price * (1.0 + (loss_pct * 2.0) / 100.0), 8)
    return {
        "stop_loss": stop,
        "take_profit": target,
        "trailing_stop": None,
        "invalidation_price": round((entry_price + stop) / 2.0, 8),
        "max_hold_hours": max_hold_h,
        "expected_hold_time": f"{max_hold_h}h",
        "exit_strategy": "emergency_loss_band_backfill",
        "dynamic_exit_levels": {
            "stop_loss": stop,
            "take_profit": target,
            "invalidation_price": round((entry_price + stop) / 2.0, 8),
            "entry_price": entry_price,
            "side": "buy",
        },
    }


def _ensure_signal_for_position(
    session: Session,
    symbol: str,
    log: Optional[ExecutionLog],
    entry_price: float,
) -> StrategySignal:
    sig, _existing_log = _entry_context_for_symbol(session, symbol)
    if sig is not None:
        return sig

    asset_class = "crypto" if "/" in display_symbol(symbol) or "USD" in symbol.upper() else "stock"
    cycle_run_id = f"self-heal-{uuid.uuid4().hex[:12]}"
    sig = StrategySignal(
        strategy="paper_self_heal",
        symbol=display_symbol(symbol) if asset_class == "crypto" else symbol,
        asset_class=asset_class,
        signal="buy",
        side="buy",
        strength=0.5,
        confidence=0.5,
        status="self_heal_backfill",
        signal_type="entry",
        cycle_run_id=cycle_run_id,
        signal_metadata={
            "self_heal_created": True,
            "entry_price": entry_price,
            "execution_log_id": getattr(log, "id", None),
            "broker_mode": "paper",
            "live_trading_locked": True,
        },
    )
    session.add(sig)
    session.flush()
    if log is not None and log.signal_id is None:
        log.signal_id = sig.id
        session.add(log)
        session.flush()
    return sig


def _persist_exit_plan_to_signal(
    session: Session,
    sig: StrategySignal,
    plan: dict[str, Any],
    *,
    source: str,
    execution_log_id: Optional[int] = None,
) -> None:
    meta = dict(sig.signal_metadata or {})
    levels = plan.get("dynamic_exit_levels")
    if isinstance(levels, dict) and levels:
        meta["dynamic_exit_levels"] = levels
    meta["exit_plan_source"] = source
    meta["self_heal_attached_at"] = _now_iso()
    meta["self_heal_execution_log_id"] = execution_log_id
    if source == "emergency_backfill":
        meta["emergency_backfill"] = True
        meta["counts_as_strategy_success"] = False
        meta["exit_strategy"] = plan.get("exit_strategy") or "emergency_paper_safety"
    else:
        meta["self_heal_recovered"] = True
        meta["exit_strategy"] = plan.get("exit_strategy") or meta.get("exit_strategy") or "recovered_exit_plan"

    if plan.get("max_hold_hours") is not None:
        meta["max_hold_hours"] = plan["max_hold_hours"]
    if plan.get("expected_hold_time"):
        meta["expected_hold_time"] = plan["expected_hold_time"]
    if plan.get("trailing_stop") is not None:
        meta["trailing_stop"] = plan["trailing_stop"]
    if plan.get("invalidation_price") is not None:
        meta["invalidation_price"] = plan["invalidation_price"]

    if plan.get("stop_loss") is not None:
        sig.stop_loss = plan["stop_loss"]
    if plan.get("take_profit") is not None:
        sig.take_profit = plan["take_profit"]
    sig.signal_metadata = meta
    session.add(sig)
    session.flush()


def _refresh_enriched_state(session: Session, symbol: str, pos: Any) -> None:
    try:
        broker_sym = _pos_symbol(pos) or symbol
        pos_dict = {
            "qty": _pos_qty(pos),
            "avg_entry_price": _f(getattr(pos, "avg_entry_price", None) if not isinstance(pos, dict) else pos.get("avg_entry_price")),
            "current_price": _f(getattr(pos, "current_price", None) if not isinstance(pos, dict) else pos.get("current_price")),
            "market_value": _f(getattr(pos, "market_value", None) if not isinstance(pos, dict) else pos.get("market_value")),
            "unrealized_pl": _f(getattr(pos, "unrealized_pl", None) if not isinstance(pos, dict) else pos.get("unrealized_pl")),
            "unrealized_pl_pct": _f(getattr(pos, "unrealized_pl_pct", None) if not isinstance(pos, dict) else pos.get("unrealized_pl_pct")),
            "side": "long",
        }
        state = build_enriched_state(session, broker_sym, pos_dict)
        state["signal_id"] = state.get("signal_id")
        state["stop_loss"] = state.get("stop_loss")
        state["take_profit"] = state.get("take_profit")
        _persist_state(session, broker_sym, state)
    except Exception:
        pass


def _heal_one_position(
    session: Session,
    config: dict,
    pos: Any,
) -> dict[str, Any]:
    sym = _pos_symbol(pos)
    qty = _pos_qty(pos)
    if not sym or qty <= 0:
        return {"symbol": sym, "status": "skipped", "reason": "no_position"}

    entry = _f(getattr(pos, "avg_entry_price", None) if not isinstance(pos, dict) else pos.get("avg_entry_price")) or 0.0
    current = _f(getattr(pos, "current_price", None) if not isinstance(pos, dict) else pos.get("current_price")) or entry
    before = resolve_exit_plan(session, config, sym, avg_entry=entry, current_price=current)
    if not before.get("missing_exit_plan"):
        return {
            "symbol": sym,
            "status": "already_protected",
            "protection_state": "protected",
            "exit_plan_source": before.get("exit_plan_source"),
            "signal_id": before.get("signal_id"),
        }

    sig, log = _entry_context_for_symbol(session, sym)
    meta = dict(getattr(sig, "signal_metadata", None) or {}) if sig else {}
    recovered = _extract_recoverable_plan(sig, meta)

    result: dict[str, Any] = {
        "symbol": sym,
        "missing_exit_plan_detected": True,
        "signal_id_before": getattr(sig, "id", None),
        "execution_log_id": getattr(log, "id", None),
        "new_entries_blocked_before": True,
    }

    if _documented_from_plan(recovered):
        if sig is None:
            sig = _ensure_signal_for_position(session, sym, log, entry)
        _persist_exit_plan_to_signal(
            session,
            sig,
            recovered,
            source="recovered_signal",
            execution_log_id=getattr(log, "id", None),
        )
        _refresh_enriched_state(session, sym, pos)
        after = resolve_exit_plan(session, config, sym, avg_entry=entry, current_price=current)
        result.update(
            {
                "status": "backfill_success",
                "backfill_success": True,
                "protection_state": "recovered plan",
                "exit_plan_source": after.get("exit_plan_source"),
                "signal_id": getattr(sig, "id", None),
                "stop_loss": after.get("stop_loss"),
                "take_profit": after.get("take_profit"),
                "new_entries_blocked_after": bool(after.get("missing_exit_plan")),
            }
        )
        return result

    if sig is None:
        sig = _ensure_signal_for_position(session, sym, log, entry)
    signal_meta = meta.get("push_pull_score") if isinstance(meta.get("push_pull_score"), dict) else meta
    emergency = _compute_emergency_plan(
        session,
        config,
        symbol=sym,
        entry_price=entry,
        current_price=current,
        signal_meta=signal_meta if isinstance(signal_meta, dict) else None,
    )
    _persist_exit_plan_to_signal(
        session,
        sig,
        emergency,
        source="emergency_backfill",
        execution_log_id=getattr(log, "id", None),
    )
    _refresh_enriched_state(session, sym, pos)
    after = resolve_exit_plan(session, config, sym, avg_entry=entry, current_price=current)
    result.update(
        {
            "status": "emergency_exit_plan_attached",
            "backfill_failed": True,
            "emergency_exit_plan_attached": True,
            "protection_state": "emergency plan",
            "exit_plan_source": after.get("exit_plan_source"),
            "signal_id": getattr(sig, "id", None),
            "stop_loss": after.get("stop_loss"),
            "take_profit": after.get("take_profit"),
            "max_hold_hours": emergency.get("max_hold_hours"),
            "new_entries_blocked_after": bool(after.get("missing_exit_plan")),
        }
    )
    return result


def _record_self_heal_audit(session: Session, summary: dict[str, Any], operator: str) -> None:
    try:
        session.add(
            SettingsActionAudit(
                action=SELF_HEAL_ACTION,
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json=summary,
            )
        )
    except Exception:
        pass


def _write_incident_memory(session: Session, config: dict, summary: dict[str, Any]) -> None:
    lessons = LessonMemoryService(session, config)
    for item in summary.get("positions") or []:
        sym = item.get("symbol") or "?"
        status = item.get("status") or "unknown"
        if status == "already_protected":
            continue
        title = f"Exit plan self-heal: {sym}"
        if item.get("backfill_success"):
            body = (
                f"Recovered exit plan for {sym} from signal/execution log "
                f"(signal_id={item.get('signal_id')})."
            )
            memory_type = "exit_plan_recovered_memory"
        elif item.get("emergency_exit_plan_attached"):
            body = (
                f"Attached emergency paper-only exit plan for {sym} "
                f"(stop={item.get('stop_loss')}, target={item.get('take_profit')}). "
                "Does not count as strategy success."
            )
            memory_type = "exit_plan_emergency_memory"
        else:
            body = f"Could not self-heal exit plan for {sym}: {status}"
            memory_type = "exit_plan_self_heal_incident"
        lessons.upsert_lesson(
            memory_type=memory_type,
            title=title,
            summary=body[:500],
            detailed_lesson=body,
            symbol=sym,
            source="exit_plan_self_heal",
            pattern_key=f"self_heal|{sym}|{datetime.utcnow().date()}|{status}",
            can_influence_ranking=False,
            visible_to_ai=True,
            category="operations_incident",
            aggregate=True,
        )


def latest_self_heal_status(session: Session) -> Optional[dict[str, Any]]:
    row = session.exec(
        select(SettingsActionAudit)
        .where(SettingsActionAudit.action == SELF_HEAL_ACTION)
        .order_by(SettingsActionAudit.created_at.desc())
    ).first()
    return dict(row.details_json or {}) if row else None


def self_heal_diagnostics(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    try:
        positions = AlpacaAdapter(session).sync_positions_cached() or []
    except Exception:
        positions = []
    unmanaged = open_positions_missing_exit_plan(session, cfg, positions)
    latest = latest_self_heal_status(session) or {}
    pos_results = latest.get("positions") or []
    recovered = [p.get("symbol") for p in pos_results if p.get("backfill_success")]
    emergency = [p.get("symbol") for p in pos_results if p.get("emergency_exit_plan_attached")]
    return {
        "status": "ok",
        "generated_at": _now_iso(),
        "unmanaged_positions": unmanaged,
        "unmanaged_count": len(unmanaged),
        "self_heal_attempts": int(latest.get("attempted", 0)),
        "last_self_heal_at": latest.get("finished_at"),
        "last_self_heal_result": latest.get("status"),
        "recovered_exit_plans": recovered,
        "emergency_exit_plans": emergency,
        "unresolved_positions": unmanaged,
        "new_entries_blocked": bool(unmanaged) and bool(
            _apl_cfg(cfg).get("block_new_entry_if_unmanaged_position", True)
        ),
        "auto_heal_enabled": self_heal_enabled(cfg),
        **live_lock_status(cfg),
    }


def attempt_exit_plan_self_heal(
    session: Session,
    config: Optional[dict] = None,
    *,
    operator: str = "autopilot",
) -> dict[str, Any]:
    """Run deterministic exit-plan self-heal for all open paper positions."""
    cfg = config or ConfigManager(session).get_current()
    started = _now_iso()

    if not self_heal_enabled(cfg):
        return {"status": "skipped", "reason": "auto_heal_disabled", "started_at": started}
    if not is_paper_broker_url():
        return {"status": "blocked", "reason": "broker_not_paper", "started_at": started}
    if bool(cfg_get(cfg, "live_trading_enabled", False)):
        return {"status": "blocked", "reason": "live_trading_must_stay_off", "started_at": started}

    try:
        positions = AlpacaAdapter(session).sync_positions_cached() or []
    except Exception:
        positions = []

    missing_before = open_positions_missing_exit_plan(session, cfg, positions)
    if not missing_before:
        summary = {
            "status": "ok",
            "message": "No unmanaged positions",
            "started_at": started,
            "finished_at": _now_iso(),
            "attempted": 0,
            "positions": [],
            "missing_before": [],
            "missing_after": [],
            "new_entries_blocked": False,
        }
        _record_self_heal_audit(session, summary, operator)
        return summary

    results: list[dict[str, Any]] = []
    for pos in positions:
        sym = _pos_symbol(pos)
        if not sym or _pos_qty(pos) <= 0:
            continue
        if not any(symbols_match(sym, m) for m in missing_before):
            continue
        results.append(_heal_one_position(session, cfg, pos))

    missing_after = open_positions_missing_exit_plan(session, cfg, positions)
    finished = _now_iso()
    summary = {
        "status": "ok" if not missing_after else "partial",
        "message": (
            f"Self-healed {len(results)} position(s); "
            f"{len(missing_after)} still unmanaged."
            if missing_after
            else f"Self-healed {len(results)} position(s); all managed."
        ),
        "started_at": started,
        "finished_at": finished,
        "attempted": len(results),
        "positions": results,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "new_entries_blocked": bool(missing_after)
        and bool(_apl_cfg(cfg).get("block_new_entry_if_unmanaged_position", True)),
        "recovered_count": sum(1 for r in results if r.get("backfill_success")),
        "emergency_count": sum(1 for r in results if r.get("emergency_exit_plan_attached")),
        "unresolved_count": len(missing_after),
    }
    _record_self_heal_audit(session, summary, operator)
    _write_incident_memory(session, cfg, summary)
    try:
        session.flush()
    except Exception:
        pass
    return summary
