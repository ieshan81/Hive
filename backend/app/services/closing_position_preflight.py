"""Full-position exit exemption from entry minimum-notional preflight (paper/training only)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, PositionSnapshot
from app.services.alpaca_adapter import normalize_crypto_symbol
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.engine_config import cfg_get, current_promotion_stage
from app.services.portfolio_gate import ApprovedCandidate

CLOSE_PURPOSES = frozenset(
    {
        "close_existing_position",
        "exit_only",
        "max_hold_exit",
        "stale_position_exit",
        "manual_operator_exit",
        "training_exit",
    }
)

PENDING_EXIT_STATUSES = (
    "paper_order_pending",
    "paper_order_submitted",
    "paper_order_partially_filled",
)


def _sym_key(symbol: str) -> str:
    return normalize_crypto_symbol(symbol).upper().replace("/", "")


def resolve_close_purpose(cand: ApprovedCandidate, portfolio_decision=None) -> Optional[str]:
    meta = cand.meta or {}
    if meta.get("purpose") in CLOSE_PURPOSES:
        return str(meta["purpose"])
    if meta.get("close_existing_position") or meta.get("training_exit"):
        return str(meta.get("purpose") or "close_existing_position")
    if cand.signal_type == "exit":
        if portfolio_decision and getattr(portfolio_decision, "portfolio_reason_code", None) == "training_exit":
            return "training_exit"
        return str(meta.get("purpose") or "close_existing_position")
    return None


def _broker_position_qty(
    positions: list,
    symbol: str,
) -> tuple[Optional[float], Optional[Any]]:
    key = _sym_key(symbol)
    for pos in positions or []:
        ps = _sym_key(getattr(pos, "symbol", "") or (pos.get("symbol") if isinstance(pos, dict) else ""))
        if ps != key:
            continue
        qty = float(getattr(pos, "qty", 0) if not isinstance(pos, dict) else pos.get("qty", 0))
        if qty > 0:
            return qty, pos
    return None, None


def qty_within_tolerance(requested: float, broker_qty: float, *, rel_tol: float = 1e-4) -> bool:
    if requested <= 0 or broker_qty <= 0:
        return False
    if requested > broker_qty * (1 + rel_tol) + 1e-8:
        return False
    return abs(requested - broker_qty) <= max(broker_qty * rel_tol, 1e-8)


def has_pending_exit_order(session: Session, symbol: str) -> bool:
    key = _sym_key(symbol)
    rows = session.exec(
        select(ExecutionLog).where(
            ExecutionLog.side == "sell",
            ExecutionLog.status.in_(list(PENDING_EXIT_STATUSES)),
        )
    ).all()
    for row in rows:
        if _sym_key(row.symbol) == key:
            return True
    return False


def broker_position_authoritative(session: Session, symbol: str, broker_qty: float) -> bool:
    key = _sym_key(symbol)
    row = session.exec(
        select(PositionSnapshot).where(PositionSnapshot.qty > 0)
    ).all()
    for pos in row:
        if _sym_key(pos.symbol) == key and float(pos.qty) > 0:
            return abs(float(pos.qty) - broker_qty) <= max(broker_qty * 1e-4, 1e-8)
    return broker_qty > 0


def evaluate_full_position_exit_exemption(
    session: Session,
    config: dict,
    *,
    cand: ApprovedCandidate,
    positions: list,
    portfolio_decision=None,
    open_order_symbols: Optional[set[str]] = None,
) -> tuple[bool, dict[str, Any]]:
    """Return (exempt, evidence). Exempt only when all closing-position rules pass."""
    evidence: dict[str, Any] = {"evaluation": "full_position_exit_exemption"}

    if cand.side.lower() != "sell":
        evidence["fail"] = "not_sell"
        return False, evidence

    asset = (cand.meta or {}).get("asset_class", "crypto")
    if str(asset).lower() != "crypto":
        evidence["fail"] = "not_crypto"
        return False, evidence

    purpose = resolve_close_purpose(cand, portfolio_decision)
    if not purpose or purpose not in CLOSE_PURPOSES:
        evidence["fail"] = "invalid_purpose"
        evidence["purpose"] = purpose
        return False, evidence
    evidence["purpose"] = purpose

    lock = live_lock_status(config)
    if lock.get("live_lock_status") != "locked":
        evidence["fail"] = "live_lock_not_locked"
        return False, evidence

    if bool(cfg_get(config, "execution.live_orders_enabled", False)):
        evidence["fail"] = "live_orders_enabled"
        return False, evidence

    if current_promotion_stage(config) != "PAPER":
        evidence["fail"] = "not_paper_stage"
        return False, evidence

    if not is_paper_broker_url():
        evidence["fail"] = "broker_not_paper"
        return False, evidence

    if not bool(cfg_get(config, "execution.paper_orders_enabled", False)):
        evidence["fail"] = "paper_orders_disabled"
        return False, evidence

    broker_qty, pos_row = _broker_position_qty(positions, cand.symbol)
    from_broker_sync = broker_qty is not None and broker_qty > 0
    meta_qty = float((cand.meta or {}).get("broker_confirmed_qty") or 0)
    if not from_broker_sync:
        if meta_qty > 0:
            broker_qty = meta_qty
        else:
            evidence["fail"] = "no_broker_qty"
            return False, evidence

    evidence["broker_confirmed_qty"] = broker_qty
    evidence["requested_qty"] = cand.position_qty
    evidence["position_source"] = "broker_sync" if from_broker_sync else "meta_broker_confirmed"

    if not qty_within_tolerance(cand.position_qty, broker_qty):
        evidence["fail"] = "qty_mismatch_not_full_close"
        evidence["is_partial"] = cand.position_qty < broker_qty * 0.9999
        return False, evidence

    if not from_broker_sync and not broker_position_authoritative(session, cand.symbol, broker_qty):
        evidence["fail"] = "position_not_broker_authoritative"
        return False, evidence

    if has_pending_exit_order(session, cand.symbol):
        evidence["fail"] = "duplicate_pending_exit"
        return False, evidence

    if open_order_symbols:
        key = _sym_key(cand.symbol)
        for sym in open_order_symbols:
            if _sym_key(sym) == key:
                evidence["fail"] = "open_order_on_symbol"
                return False, evidence

    evidence["execution_path"] = "PaperExecutionService"
    evidence["exemption_code"] = "EXIT_FULL_POSITION_MIN_NOTIONAL_EXEMPT"
    evidence["reducing_exposure"] = True
    return True, evidence


def notional_from_candidate(cand: ApprovedCandidate, quote: Optional[dict]) -> float:
    price = float(cand.entry_price or 0)
    if price <= 0 and quote:
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid and ask:
            price = (float(bid) + float(ask)) / 2
        elif ask:
            price = float(ask)
        elif bid:
            price = float(bid)
    if price <= 0:
        price = float((cand.meta or {}).get("current_price") or 0)
    return float(cand.position_qty) * price
