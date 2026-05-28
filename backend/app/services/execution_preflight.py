"""Final preflight before Alpaca paper order submission."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, StrategySignal
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.capital_buckets import compute_buckets
from app.services.cost_edge_gate import evaluate_cost_edge
from app.services.cooldown_service import CooldownService
from app.services.engine_config import cfg_get, current_promotion_stage
from app.services.kill_switch_service import KillSwitchService
from app.services.closing_position_preflight import (
    evaluate_full_position_exit_exemption,
    notional_from_candidate,
    qty_within_tolerance,
    resolve_close_purpose,
    _broker_position_qty,
)
from app.services.portfolio_gate import ApprovedCandidate, _stage_portfolio_value


@dataclass
class PreflightResult:
    passed: bool
    block_reason_code: Optional[str] = None
    human_reason: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    client_order_id: Optional[str] = None
    limit_price: Optional[float] = None
    quote: dict[str, Any] = field(default_factory=dict)


def build_client_order_id(cycle_run_id: str, signal_id: int, side: str, symbol: str) -> str:
    short = cycle_run_id.replace("-", "")[:8]
    sym = symbol.upper().replace("/", "").replace("-", "")
    return f"CHQ-{short}-{signal_id}-{side.lower()}-{sym}"[:48]


def _orders_in_window(session: Session, *, hours: float = 0, days: float = 0) -> int:
    since = datetime.utcnow()
    if days:
        since -= timedelta(days=days)
    elif hours:
        since -= timedelta(hours=hours)
    else:
        return 0
    rows = session.exec(
        select(ExecutionLog).where(
            ExecutionLog.submitted_at >= since,
            ExecutionLog.status.in_(
                [
                    "paper_order_submitted",
                    "paper_order_filled",
                    "paper_order_partially_filled",
                ]
            ),
        )
    ).all()
    return len(rows)


def _cycle_orders(session: Session, cycle_run_id: str) -> int:
    rows = session.exec(
        select(ExecutionLog).where(
            ExecutionLog.cycle_run_id == cycle_run_id,
            ExecutionLog.status.in_(
                [
                    "paper_order_submitted",
                    "paper_order_pending",
                    "paper_order_filled",
                    "paper_order_partially_filled",
                ]
            ),
        )
    ).all()
    return len(rows)


def _signal_already_submitted(session: Session, signal_id: int) -> bool:
    row = session.exec(
        select(ExecutionLog).where(
            ExecutionLog.signal_id == signal_id,
            ExecutionLog.status.in_(
                [
                    "paper_order_submitted",
                    "paper_order_pending",
                    "paper_order_filled",
                    "paper_order_partially_filled",
                ]
            ),
        )
    ).first()
    return row is not None


def _unlimited_int(value: Any) -> bool:
    if value is None:
        return True
    try:
        return int(value) <= 0
    except (TypeError, ValueError):
        return False


def _has_exit_plan(sig: StrategySignal, meta: dict) -> bool:
    if meta.get("expected_hold_time") or meta.get("exit_strategy"):
        return True
    if sig.take_profit is not None:
        return True
    if meta.get("invalidation_reason"):
        return True
    if meta.get("entry_reason") and "exit" in str(meta.get("entry_reason", "")).lower():
        return True
    return bool(meta.get("max_hold_hours") or meta.get("expected_hold_time"))


def _paper_exploration_cost_override(config: dict, meta: dict, *, formula_paper_mode: bool) -> bool:
    nested_score = meta.get("push_pull_score") or {}
    exp = config.get("exploration") or {}
    execution = config.get("execution") or {}
    live_orders = bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))
    levels = meta.get("dynamic_exit_levels") or nested_score.get("dynamic_exit_levels") or {}
    has_exit_truth = all(levels.get(k) is not None for k in ("stop_loss", "take_profit", "trailing_stop", "invalidation_price"))
    marked_probe = bool(
        meta.get("paper_exploration_probe")
        or nested_score.get("paper_exploration_probe")
        or meta.get("paper_exploration")
        or nested_score.get("paper_exploration")
    )
    return formula_paper_mode and bool(exp.get("enabled", True)) and not live_orders and marked_probe and has_exit_truth


def run_preflight(
    session: Session,
    config: dict,
    *,
    cand: ApprovedCandidate,
    cycle_run_id: str,
    portfolio_decision,
    account,
    positions: list,
    open_order_symbols: set[str],
    alpaca,
    quote: Optional[dict],
    signal_row: Optional[StrategySignal] = None,
) -> PreflightResult:
    evidence: dict[str, Any] = {"cycle_run_id": cycle_run_id, "signal_id": cand.signal_id}
    meta = cand.meta or {}

    if not bool(cfg_get(config, "execution.paper_orders_enabled", False)):
        return PreflightResult(False, "PAPER_EXECUTION_DISABLED", "Paper orders disabled", evidence)

    if bool(cfg_get(config, "execution.live_orders_enabled", False)):
        return PreflightResult(False, "LIVE_TRADING_LOCKED", "Live trading locked", evidence)

    if current_promotion_stage(config) != "PAPER":
        return PreflightResult(False, "LIVE_TRADING_LOCKED", "Promotion stage is not PAPER", evidence)

    if not is_paper_broker_url():
        return PreflightResult(False, "BROKER_NOT_PAPER", "Alpaca base URL is not paper-api", evidence)

    ks = KillSwitchService(session, config)
    entries_ok, switches = ks.evaluate(
        equity=account.equity if account else 0,
        daily_pl_pct=account.daily_pl_pct if account else 0,
        drawdown_pct=account.drawdown_pct if account else 0,
    )
    if not entries_ok and cand.signal_type == "entry":
        return PreflightResult(
            False,
            "KILL_SWITCH_ACTIVE",
            switches[0].get("message") if switches else "Kill switch active",
            {**evidence, "switches": switches},
        )

    cd = CooldownService(session, config)
    ok, reason, cd_ev = cd.check_account()
    if not ok:
        return PreflightResult(False, "ACCOUNT_COOLDOWN_ACTIVE", reason, {**evidence, **(cd_ev or {})})
    ok, reason, cd_ev = cd.check_symbol(cand.symbol)
    if not ok:
        return PreflightResult(False, "SYMBOL_COOLDOWN_ACTIVE", reason, {**evidence, **(cd_ev or {})})

    if cand.signal_type == "observation":
        return PreflightResult(False, "OBSERVATION_NOT_EXECUTABLE", "Observations cannot execute", evidence)

    if portfolio_decision is None or not portfolio_decision.selected_for_execution:
        return PreflightResult(False, "SIGNAL_NOT_SELECTED", "Not selected by portfolio gate", evidence)

    if portfolio_decision.portfolio_rank != 1 and cand.signal_type == "entry":
        return PreflightResult(
            False,
            "SIGNAL_NOT_SELECTED",
            f"Portfolio rank {portfolio_decision.portfolio_rank} is not Top-1",
            evidence,
        )

    if portfolio_decision.portfolio_status == "portfolio_deferred":
        return PreflightResult(False, "PORTFOLIO_DEFERRED", portfolio_decision.human_reason, evidence)

    sig = signal_row
    if sig and sig.status in ("blocked", "risk_blocked", "portfolio_blocked"):
        return PreflightResult(False, "RISK_BLOCKED", sig.status, evidence)

    if cand.symbol in open_order_symbols:
        return PreflightResult(False, "DUPLICATE_OPEN_ORDER", f"Open order exists for {cand.symbol}", evidence)

    client_id = build_client_order_id(cycle_run_id, cand.signal_id, cand.side, cand.symbol)
    evidence["client_order_id"] = client_id

    existing = session.exec(
        select(OrderRecord).where(OrderRecord.broker_client_order_id == client_id)
    ).first()
    if existing:
        return PreflightResult(False, "DUPLICATE_CLIENT_ORDER_ID", "Order already in local DB", evidence)

    if _signal_already_submitted(session, cand.signal_id):
        return PreflightResult(False, "DUPLICATE_CLIENT_ORDER_ID", "Signal already submitted", evidence)

    formula_paper_mode = bool(cfg_get(config, "autonomous_paper_learning.mode_enabled", False)) and bool(
        cfg_get(config, "autonomous_paper_learning.use_capital_allocator", True)
    )

    max_cycle_raw = 0 if formula_paper_mode else cfg_get(config, "execution.max_orders_per_cycle", 1)
    max_cycle = int(max_cycle_raw or 0)
    if not _unlimited_int(max_cycle_raw) and _cycle_orders(session, cycle_run_id) >= max_cycle:
        return PreflightResult(False, "ORDER_RATE_LIMIT_REACHED", "max_orders_per_cycle", evidence)

    max_hour_raw = 0 if formula_paper_mode else cfg_get(config, "execution.max_orders_per_hour", 5)
    max_hour = int(max_hour_raw or 0)
    if not _unlimited_int(max_hour_raw) and _orders_in_window(session, hours=1) >= max_hour:
        return PreflightResult(False, "ORDER_RATE_LIMIT_REACHED", "max_orders_per_hour", evidence)

    max_day_raw = 0 if formula_paper_mode else cfg_get(config, "execution.max_orders_per_day", 20)
    max_day = int(max_day_raw or 0)
    if not _unlimited_int(max_day_raw) and _orders_in_window(session, days=1) >= max_day:
        return PreflightResult(False, "ORDER_RATE_LIMIT_REACHED", "max_orders_per_day", evidence)

    if not quote or quote.get("bid") is None or quote.get("ask") is None:
        return PreflightResult(False, "STALE_QUOTE", "No fresh quote", evidence)

    quote_age = quote.get("quote_age_seconds")
    max_age = int(cfg_get(config, "execution.quote_max_age_seconds", 30))
    if quote_age is not None and quote_age > max_age:
        return PreflightResult(False, "STALE_QUOTE", f"Quote age {quote_age}s > {max_age}s", evidence)

    spread = quote.get("spread_pct") or cand.spread_pct
    max_spread = float(config.get("max_spread_pct", 0.005))
    if spread is not None and spread > max_spread:
        return PreflightResult(False, "SPREAD_WIDENED", f"Spread {spread:.4f} > max", evidence)

    exp_move = cand.expected_move_pct or meta.get("expected_move_pct")
    if exp_move is None and meta.get("training_trade"):
        cpp = config.get("crypto_push_pull") or {}
        exp_move = float(cpp.get("take_profit_pct", 0.03)) * 100.0
    cost = evaluate_cost_edge(
        config,
        expected_move_pct=exp_move,
        spread_pct=spread,
        tier=cand.tier,
    )
    if not cost.passed and cand.signal_type == "entry":
        if _paper_exploration_cost_override(config, meta, formula_paper_mode=formula_paper_mode):
            evidence["paper_exploration_cost_override"] = {
                "original_block_reason_code": cost.block_reason_code,
                "human_reason": cost.human_reason,
                "mode": "paper_probe_dynamic_exit_truth",
            }
        else:
            return PreflightResult(False, "EDGE_BELOW_COST", cost.human_reason, {**evidence, "cost": cost.evidence})

    if cand.signal_type == "entry":
        if cand.stop_loss is None and (sig is None or sig.stop_loss is None):
            return PreflightResult(False, "MISSING_STOP_LOSS", "Stop loss required", evidence)
        if sig and not _has_exit_plan(sig, meta):
            return PreflightResult(False, "MISSING_EXIT_PLAN", "Exit/invalidation plan required", evidence)

    equity = account.equity if account else 0
    reserve_pct = _stage_portfolio_value(config, "reserve_cash_pct", 60.0)
    buckets = compute_buckets(equity, config)
    if (
        account
        and account.cash < equity * (reserve_pct / 100.0)
        and cand.signal_type == "entry"
        and not formula_paper_mode
    ):
        return PreflightResult(False, "RESERVE_CASH_REQUIRED", "Reserve cash not met", evidence)

    if cand.position_qty <= 0:
        return PreflightResult(False, "INVALID_QTY", "Quantity invalid", evidence)

    notional = notional_from_candidate(cand, quote)
    min_notional = float(cfg_get(config, "min_order_notional_usd", 1.0))
    if cand.symbol and "/" in cand.symbol:
        min_notional = max(
            min_notional,
            float(cfg_get(config, "execution.alpaca_crypto_min_notional_usd", 10.0)),
        )
    evidence["notional_usd"] = round(notional, 4)
    evidence["min_order_notional_usd"] = min_notional

    is_buy = cand.side.lower() == "buy" or cand.signal_type == "entry"
    is_sell = cand.side.lower() == "sell"

    if is_buy and notional < min_notional:
        return PreflightResult(
            False,
            "ENTRY_MIN_NOTIONAL_BLOCK",
            f"Entry notional ${notional:.2f} below minimum ${min_notional:.2f}",
            {**evidence, "preflight_stage": "internal_preflight_block"},
        )

    if is_sell:
        exempt, exempt_ev = evaluate_full_position_exit_exemption(
            session,
            config,
            cand=cand,
            positions=positions,
            portfolio_decision=portfolio_decision,
            open_order_symbols=open_order_symbols,
        )
        evidence.update(exempt_ev)
        if exempt:
            evidence["notional_exemption"] = "EXIT_FULL_POSITION_MIN_NOTIONAL_EXEMPT"
            evidence["preflight_stage"] = "full_position_exit_exempt"
        elif notional < min_notional:
            broker_qty, _ = _broker_position_qty(positions, cand.symbol)
            partial = (
                broker_qty is not None
                and broker_qty > 0
                and not qty_within_tolerance(cand.position_qty, broker_qty)
            )
            if partial:
                return PreflightResult(
                    False,
                    "EXIT_MIN_NOTIONAL_BLOCK",
                    f"Partial exit notional ${notional:.2f} below minimum ${min_notional:.2f}",
                    {**evidence, "preflight_stage": "internal_preflight_block"},
                )
            fail = exempt_ev.get("fail", "exemption_denied")
            return PreflightResult(
                False,
                "EXIT_MIN_NOTIONAL_BLOCK",
                f"Exit blocked: {fail}; notional ${notional:.2f}",
                {**evidence, "preflight_stage": "internal_preflight_block"},
            )
    elif notional < min_notional:
        return PreflightResult(
            False,
            "ENTRY_MIN_NOTIONAL_BLOCK",
            f"Notional ${notional:.2f} below minimum ${min_notional:.2f}",
            {**evidence, "preflight_stage": "internal_preflight_block"},
        )

    if cand.signal_type == "entry" and account:
        if notional > account.buying_power:
            return PreflightResult(False, "INSUFFICIENT_BUYING_POWER", "Insufficient buying power", evidence)
        if notional > buckets.crypto_night_bucket:
            return PreflightResult(False, "CRYPTO_BUCKET_EXCEEDED", "Exceeds crypto bucket", evidence)

    from app.services.execution_policy import ExecutionPolicy
    from app.services.symbol_tier_service import SymbolTierService

    policy = ExecutionPolicy(session, config, alpaca, SymbolTierService(config))
    bid, ask = quote["bid"], quote["ask"]
    limit_px = policy.limit_price(cand.side, bid, ask, cand.tier)

    return PreflightResult(
        passed=True,
        evidence={**evidence, "preflight": "passed", "cost": cost.evidence},
        client_order_id=client_id,
        limit_price=limit_px,
        quote=quote,
    )
