"""Exit monitor — always-on position watch status with real per-position exit plans.

Read-only status + plan resolution. Nothing here places, cancels, or mutates
orders; the actual exit execution lives in
``TrainingExecutionService.monitor_exits`` which routes every sell through the
ExecutionCage (paper-only). This module only *reads* the opening signal for each
held position and reconstructs its documented exit plan
(entry / stop-loss / take-profit / trailing / invalidation / max-hold), then
flags any position that lacks one as ``missing_exit_plan``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, PositionSnapshot, StrategySignal
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.paper_autopilot_caps import LIVE_OR_FILLED_STATUSES
from app.services.symbol_normalize import symbol_variants, symbols_match
from app.services.training_execution_service import TrainingExecutionService


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pos_symbol(pos: Any) -> str:
    if isinstance(pos, dict):
        return str(pos.get("symbol") or pos.get("sym") or "")
    return str(getattr(pos, "symbol", "") or "")


def _pos_qty(pos: Any) -> float:
    try:
        if isinstance(pos, dict):
            return float(pos.get("qty", 0) or 0)
        return float(getattr(pos, "qty", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _entry_context_for_symbol(session: Session, symbol: str):
    """Return (StrategySignal | None, ExecutionLog | None) for the latest entry of a held symbol.

    Prefers the signal tied to the most recent live/filled BUY execution log;
    falls back to the latest entry signal row for the symbol (variant-aware).
    """
    variants = {v.upper() for v in symbol_variants(symbol)}
    logs = list(
        session.exec(
            select(ExecutionLog)
            .where(
                ExecutionLog.side == "buy",
                ExecutionLog.status.in_(list(LIVE_OR_FILLED_STATUSES)),
            )
            .order_by(ExecutionLog.submitted_at.desc(), ExecutionLog.id.desc())
        ).all()
    )
    log = next((row for row in logs if str(row.symbol or "").upper() in variants), None)
    sig = None
    if log is not None and log.signal_id is not None:
        sig = session.get(StrategySignal, log.signal_id)
    if sig is None:
        rows = list(
            session.exec(
                select(StrategySignal)
                .where(StrategySignal.signal_type == "entry")
                .order_by(StrategySignal.created_at.desc())
            ).all()
        )
        sig = next((row for row in rows if symbols_match(row.symbol or "", symbol)), None)
    return sig, log


def resolve_exit_plan(
    session: Session,
    config: dict,
    symbol: str,
    *,
    avg_entry: float = 0.0,
    current_price: float = 0.0,
) -> dict[str, Any]:
    """Reconstruct the documented exit plan for one held symbol.

    A position is considered *managed* (``has_exit_plan``) when the opening
    signal carried at least one explicit exit lever: stop-loss, take-profit,
    trailing stop, invalidation price, or a max-hold horizon. The config-derived
    hard-safety stop is reported as a backstop but does NOT, on its own, count as
    a real per-position plan (so an un-thesised position still trips the flag).
    """
    sig, log = _entry_context_for_symbol(session, symbol)
    meta = dict(getattr(sig, "signal_metadata", None) or {}) if sig else {}
    levels = meta.get("dynamic_exit_levels") or {}

    stop_loss = (_f(getattr(sig, "stop_loss", None)) if sig else None) or _f(levels.get("stop_loss"))
    take_profit = (_f(getattr(sig, "take_profit", None)) if sig else None) or _f(levels.get("take_profit"))
    trailing = _f(levels.get("trailing_stop")) or _f(meta.get("trailing_stop"))
    invalidation = _f(levels.get("invalidation_price")) or _f(meta.get("invalidation_price"))
    max_hold_hours = _f(meta.get("max_hold_hours")) or _f(meta.get("expected_hold_hours"))
    expected_hold_time = meta.get("expected_hold_time")

    entry_price = (
        _f(avg_entry)
        or (_f(log.filled_avg_price) if log else None)
        or _f(meta.get("entry_price"))
    )

    apl = config.get("autonomous_paper_learning") or {}
    hard_stop_pct = _f(apl.get("max_unrealized_loss_pct"))
    hard_stop_usd = _f(apl.get("max_unrealized_loss_usd"))
    hard_safety_stop_price = None
    if entry_price and hard_stop_pct:
        hard_safety_stop_price = round(entry_price * (1.0 - hard_stop_pct / 100.0), 8)

    documented = any(
        [
            stop_loss is not None,
            take_profit is not None,
            trailing is not None,
            invalidation is not None,
            max_hold_hours is not None,
            bool(expected_hold_time),
            bool(meta.get("exit_strategy")),
            bool(meta.get("invalidation_reason")),
        ]
    )

    exit_plan_source = "none"
    if documented and sig is not None:
        stored_source = str(meta.get("exit_plan_source") or "").strip()
        if meta.get("emergency_backfill") or stored_source == "emergency_backfill":
            exit_plan_source = "emergency_backfill"
        elif meta.get("self_heal_recovered") or stored_source == "recovered_signal":
            exit_plan_source = "recovered_signal"
        elif stored_source and stored_source not in ("none", ""):
            exit_plan_source = stored_source
        else:
            exit_plan_source = "entry_signal"

    protection_state = "unmanaged"
    if documented:
        if exit_plan_source == "emergency_backfill":
            protection_state = "emergency plan"
        elif exit_plan_source == "recovered_signal":
            protection_state = "recovered plan"
        else:
            protection_state = "protected"

    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "current_price": _f(current_price),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trailing_stop": trailing,
        "invalidation_price": invalidation,
        "max_hold_hours": max_hold_hours,
        "expected_hold_time": expected_hold_time,
        "hard_safety_stop_pct": hard_stop_pct,
        "hard_safety_stop_usd": hard_stop_usd,
        "hard_safety_stop_price": hard_safety_stop_price,
        "has_exit_plan": bool(documented),
        "missing_exit_plan": not bool(documented),
        "exit_plan_source": exit_plan_source,
        "protection_state": protection_state,
        "self_heal_attached_at": meta.get("self_heal_attached_at"),
        "emergency_backfill": bool(meta.get("emergency_backfill")),
        "signal_id": getattr(sig, "id", None),
    }


def open_positions_missing_exit_plan(
    session: Session,
    config: dict,
    positions: Optional[list] = None,
) -> list[str]:
    """Symbols of currently-open positions that have no documented exit plan.

    Used by the entry preflight to refuse opening *new* risk while an existing
    position is unmanaged. Read-only.
    """
    if positions is None:
        try:
            positions = AlpacaAdapter(session).sync_positions_cached() or []
        except Exception:
            positions = []
    missing: list[str] = []
    for pos in positions or []:
        sym = _pos_symbol(pos)
        if not sym or _pos_qty(pos) <= 0:
            continue
        plan = resolve_exit_plan(
            session,
            config,
            sym,
            avg_entry=_f(getattr(pos, "avg_entry_price", None) if not isinstance(pos, dict) else pos.get("avg_entry_price")) or 0.0,
        )
        if plan["missing_exit_plan"]:
            missing.append(sym)
    return missing


def exit_monitor_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    alpaca = AlpacaAdapter(session)
    positions = alpaca.sync_positions_cached() or []
    training = TrainingExecutionService(session, cfg)
    monitor = training.monitor_exits()

    plans: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    for pos in positions:
        qty = _pos_qty(pos)
        if qty <= 0:
            continue
        sym = _pos_symbol(pos)
        entry = float(getattr(pos, "avg_entry_price", 0) or 0)
        current = float(getattr(pos, "current_price", 0) or 0)
        upl = float(getattr(pos, "unrealized_pl", 0) or 0)
        plan = resolve_exit_plan(session, cfg, sym, avg_entry=entry, current_price=current)
        plan.update({"qty": qty, "unrealized_pl": upl})
        if plan["missing_exit_plan"]:
            missing_symbols.append(sym)
        plans.append(plan)

    require_monitor = bool((cfg.get("paper_learning") or {}).get("require_position_monitor", True))
    block_unmanaged = bool(
        (cfg.get("autonomous_paper_learning") or {}).get("block_new_entry_if_unmanaged_position", True)
    )
    from app.services.exit_plan_self_heal_service import latest_self_heal_status, self_heal_diagnostics

    self_heal = latest_self_heal_status(session) or {}
    heal_diag = self_heal_diagnostics(session, cfg)
    return {
        "status": "ok",
        "schema_version": 3,
        "exit_monitor_enabled": True,
        "require_exit_monitor": require_monitor,
        "block_new_entry_if_unmanaged_position": block_unmanaged,
        "open_positions_count": len(plans),
        "positions": plans,
        "any_missing_exit_plan": bool(missing_symbols),
        "missing_exit_plan_symbols": missing_symbols,
        "latest_monitor_run": monitor,
        "self_heal": {
            "auto_heal_enabled": heal_diag.get("auto_heal_enabled"),
            "last_attempt_at": self_heal.get("finished_at"),
            "last_result": self_heal.get("status"),
            "last_message": self_heal.get("message"),
            "attempted": self_heal.get("attempted"),
            "recovered_count": self_heal.get("recovered_count"),
            "emergency_count": self_heal.get("emergency_count"),
            "unresolved_count": heal_diag.get("unmanaged_count"),
        },
        "self_heal_diagnostics": heal_diag,
        "live_locked": True,
        "broker_mode": "paper",
        "plain": (
            f"Watching {len(plans)} open position(s) for exit triggers."
            + (f" {len(missing_symbols)} lack a documented exit plan." if missing_symbols else "")
            if plans
            else "No open positions — exit monitor idle."
        ),
    }
