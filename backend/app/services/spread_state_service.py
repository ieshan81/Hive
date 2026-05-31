"""Spread state — entry-side cooldown/rotation + exit-side escalation. Paper-only.

Two separated policies over the same per-symbol :class:`SymbolSpreadState`:

* **Entry** (strict): repeated ``SPREAD_WIDENED`` on a symbol trips a cooldown so the
  scanner rotates to the next candidate instead of retrying the same wide-spread symbol.
* **Exit** (never trap): a stop-loss / invalidation / emergency exit is **never** spread
  blocked; a soft (time-stop / stale / fee-negative / take-profit) exit is allowed up to a
  widened tolerance, may briefly **delay** beyond that, and **escalates** (forced through +
  freezes new entries) after repeated failed attempts so a position can never loop forever.

Pure decision helpers + defensive DB read/write. Nothing here places, cancels, or mutates
a broker order — it returns verdicts the execution cage / scanner consult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import SymbolSpreadState

SPREAD_DEFAULTS: dict[str, Any] = {
    # Entry cooldown / rotation
    "spread_widened_repeat_threshold": 3,      # blocks within lookback before cooldown
    "spread_widened_lookback_minutes": 30,
    "spread_cooldown_minutes": 30,
    # Exit escalation
    "exit_spread_tolerance_multiplier": 3.0,   # soft exits allowed up to N x entry max_spread
    "max_exit_spread_delay_minutes": 10,       # after this, a soft exit escalates
    "max_failed_exit_attempts_before_escalation": 3,
    "freeze_new_entries_on_unresolved_exit": True,
}

# Reasons that must NEVER be trapped by spread (controlled exit always proceeds).
# Precise tokens — a "time_stop" / "max_hold" is a SOFT exit, not a protective stop.
_HARD_EXIT_KEYS = ("stop_loss", "stoploss", "stop loss", "invalidat", "emergency", "liquidat", "kill_switch")


def spread_cfg(config: dict) -> dict[str, Any]:
    apl = (config or {}).get("autonomous_paper_learning") or {}
    raw = apl.get("spread_policy") or {}
    merged = dict(SPREAD_DEFAULTS)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if v is not None})
    return merged


def norm_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "")


def classify_exit_urgency(meta: Optional[dict], signal_type: Optional[str], side: Optional[str]) -> Optional[str]:
    """Return 'hard' | 'soft' for an exit/sell, else None for an entry/buy."""
    is_exit = str(side or "").lower() == "sell" or str(signal_type or "") == "exit"
    if not is_exit:
        return None
    m = meta or {}
    reason = str(m.get("exit_reason") or m.get("reason") or m.get("purpose") or "").lower()
    if any(k in reason for k in _HARD_EXIT_KEYS):
        return "hard"
    return "soft"


# ───────────────────────── state read/write (defensive) ─────────────────────────
def get_state(session: Session, symbol: str) -> Optional[SymbolSpreadState]:
    try:
        return session.get(SymbolSpreadState, norm_symbol(symbol))
    except Exception:
        return None


def _row(session: Session, symbol: str) -> SymbolSpreadState:
    key = norm_symbol(symbol)
    row = session.get(SymbolSpreadState, key)
    if row is None:
        row = SymbolSpreadState(symbol=key)
        session.add(row)
    return row


def _write_spread_lesson(session: Session, config: dict, symbol: str, count: int) -> None:
    """Repeated SPREAD_WIDENED on a symbol becomes a visible learned lesson (fail-safe)."""
    try:
        from app.services.lesson_memory_service import LessonMemoryService

        LessonMemoryService(session, config).upsert_lesson(
            memory_type="spread_widened_pattern",
            title=f"Spread too wide repeatedly: {symbol}",
            summary=f"{symbol} hit SPREAD_WIDENED {count}x within the lookback window — entries "
            "cooled down and the scanner rotates to other candidates.",
            detailed_lesson="Repeated wide-spread entries waste cycles and signal poor liquidity; "
            "rotate away rather than retrying the same symbol.",
            symbol=symbol,
            source="spread_state_service",
            pattern_key=f"spread_widened|{norm_symbol(symbol)}",
            can_influence_ranking=False,
            visible_to_ai=True,
        )
    except Exception:
        pass  # lesson writing must never break the cage


# ───────────────────────── entry cooldown / rotation (TASK 2) ─────────────────────────
def is_entry_cooldown_active(session: Session, config: dict, symbol: str) -> tuple[bool, dict[str, Any]]:
    row = get_state(session, symbol)
    if not row or not row.spread_cooldown_until:
        return False, {"spread_cooldown_active": False}
    active = row.spread_cooldown_until > datetime.utcnow()
    return active, {
        "spread_cooldown_active": active,
        "spread_cooldown_until": row.spread_cooldown_until.isoformat() + "Z",
        "spread_widened_count": row.spread_widened_count,
    }


def record_spread_widened(session: Session, config: dict, symbol: str) -> dict[str, Any]:
    """Increment the symbol's spread-widened counter; trip a cooldown once it repeats."""
    cfg = spread_cfg(config)
    now = datetime.utcnow()
    lookback = timedelta(minutes=float(cfg["spread_widened_lookback_minutes"]))
    try:
        row = _row(session, symbol)
        # Reset the counter if the last block was outside the lookback window.
        if row.last_spread_widened_at and (now - row.last_spread_widened_at) > lookback:
            row.spread_widened_count = 0
        row.spread_widened_count += 1
        row.last_spread_widened_at = now
        cooled = False
        if row.spread_widened_count >= int(cfg["spread_widened_repeat_threshold"]):
            row.spread_cooldown_until = now + timedelta(minutes=float(cfg["spread_cooldown_minutes"]))
            cooled = True
        row.updated_at = now
        session.add(row)
        if cooled:
            _write_spread_lesson(session, config, symbol, row.spread_widened_count)
        return {
            "spread_widened_count": row.spread_widened_count,
            "cooldown_tripped": cooled,
            "spread_cooldown_until": row.spread_cooldown_until.isoformat() + "Z" if row.spread_cooldown_until else None,
        }
    except Exception as exc:  # never break the cage
        return {"spread_state_error": type(exc).__name__}


# ───────────────────────── exit spread policy (TASK 3) ─────────────────────────
@dataclass
class ExitSpreadDecision:
    action: str  # "allow" | "delay" | "escalate"
    code: str
    evidence: dict[str, Any] = field(default_factory=dict)
    freeze_entries: bool = False


def evaluate_exit_spread(
    session: Session,
    config: dict,
    *,
    symbol: str,
    urgency: str,
    spread: float,
    max_spread: float,
) -> ExitSpreadDecision:
    """Decide whether an exit may proceed despite a wide spread. Hard exits always allow."""
    cfg = spread_cfg(config)
    if urgency == "hard":
        clear_failed_exit(session, symbol)
        return ExitSpreadDecision("allow", "EXIT_SPREAD_BYPASS_HARD", {"urgency": "hard", "spread": spread})

    tolerant_max = float(max_spread) * float(cfg["exit_spread_tolerance_multiplier"])
    if spread <= tolerant_max:
        clear_failed_exit(session, symbol)
        return ExitSpreadDecision(
            "allow", "EXIT_SPREAD_WITHIN_TOLERANCE",
            {"urgency": "soft", "spread": spread, "tolerant_max": round(tolerant_max, 6)},
        )

    # Spread beyond even the exit tolerance — count the failed attempt and decide delay vs escalate.
    now = datetime.utcnow()
    attempts = 1
    first_at: Optional[datetime] = now
    try:
        row = _row(session, symbol)
        row.failed_exit_attempts = int(row.failed_exit_attempts or 0) + 1
        if not row.first_failed_exit_at:
            row.first_failed_exit_at = now
        row.last_failed_exit_at = now
        row.updated_at = now
        session.add(row)
        attempts = row.failed_exit_attempts
        first_at = row.first_failed_exit_at
    except Exception as exc:
        return ExitSpreadDecision("delay", "EXIT_DELAYED_SPREAD_WIDE", {"spread_state_error": type(exc).__name__})

    max_attempts = int(cfg["max_failed_exit_attempts_before_escalation"])
    delay_exceeded = bool(first_at and (now - first_at).total_seconds() / 60.0 >= float(cfg["max_exit_spread_delay_minutes"]))
    ev = {
        "urgency": "soft",
        "spread": spread,
        "tolerant_max": round(tolerant_max, 6),
        "failed_exit_attempts": attempts,
        "max_attempts": max_attempts,
        "delay_exceeded": delay_exceeded,
    }
    if attempts >= max_attempts or delay_exceeded:
        return ExitSpreadDecision(
            "escalate", "EXIT_ESCALATED_AFTER_SPREAD_BLOCK", ev,
            freeze_entries=bool(cfg["freeze_new_entries_on_unresolved_exit"]),
        )
    return ExitSpreadDecision("delay", "EXIT_DELAYED_SPREAD_WIDE", ev)


def clear_failed_exit(session: Session, symbol: str) -> None:
    """Exit resolved (filled / hard exit) — reset its failed-attempt escalation state."""
    try:
        row = get_state(session, symbol)
        if row and (row.failed_exit_attempts or row.first_failed_exit_at):
            row.failed_exit_attempts = 0
            row.first_failed_exit_at = None
            row.updated_at = datetime.utcnow()
            session.add(row)
    except Exception:
        pass


def unresolved_exit_freeze(session: Session, config: dict) -> tuple[bool, list[str]]:
    """True + offending symbols when an escalated exit is unresolved and entries are frozen."""
    cfg = spread_cfg(config)
    if not bool(cfg["freeze_new_entries_on_unresolved_exit"]):
        return False, []
    threshold = int(cfg["max_failed_exit_attempts_before_escalation"])
    try:
        rows = session.exec(
            select(SymbolSpreadState).where(SymbolSpreadState.failed_exit_attempts >= threshold)
        ).all()
        syms = [r.symbol for r in rows]
        return (len(syms) > 0), syms
    except Exception:
        return False, []


# ───────────────────────── diagnostics ─────────────────────────
def spread_diagnostics(session: Session, config: dict) -> dict[str, Any]:
    now = datetime.utcnow()
    try:
        rows = list(session.exec(select(SymbolSpreadState)).all())
    except Exception:
        rows = []
    count_by_symbol = {r.symbol: r.spread_widened_count for r in rows if r.spread_widened_count}
    cooldown_syms = [r.symbol for r in rows if r.spread_cooldown_until and r.spread_cooldown_until > now]
    cooldown_until = {
        r.symbol: r.spread_cooldown_until.isoformat() + "Z"
        for r in rows
        if r.spread_cooldown_until and r.spread_cooldown_until > now
    }
    frozen, frozen_syms = unresolved_exit_freeze(session, config)
    return {
        "spread_widened_count_by_symbol": count_by_symbol,
        "spread_cooldown_symbols": cooldown_syms,
        "spread_cooldown_until": cooldown_until,
        "spread_rotation_active": len(cooldown_syms) > 0,
        "failed_exit_attempts_by_symbol": {r.symbol: r.failed_exit_attempts for r in rows if r.failed_exit_attempts},
        "new_entries_frozen_on_unresolved_exit": frozen,
        "frozen_exit_symbols": frozen_syms,
    }
