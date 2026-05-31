"""Adaptive opportunity budget — risk-based entry gate.

This REPLACES the old fixed daily trade-count blocker (``absolute_max_new_entries_per_day``)
as the thing that decides whether *one more* new paper entry is allowed. Instead of
"stop after N trades/day", a new entry is allowed only when the **risk budget, edge
after cost, broker health, reconciliation, and protection guards** all pass.

Paper-only. Deterministic. **Never** places, sizes-up, or mutates an order — it returns
an allow/block verdict that the execution cage (``execution_preflight``) consults. The
existing hard safety gates (live-lock, paper-broker, kill switch, max open positions,
duplicate-buy, missing-exit-plan, stale-quote, spread, buying power) are unchanged and
still run independently; this module does not weaken any of them.

A generous **circuit-breaker** ceiling (``absolute_max_orders_per_day``, default high)
remains so a runaway loop can never place unlimited orders — that is a safety sanity
bound, not a trade-count strategy cap.

Split for testability: :func:`evaluate_opportunity_budget` is a pure function over
:class:`BudgetInputs`; :func:`collect_budget_inputs` / :func:`decide_entry` do the
defensive DB/account reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog
from app.services.paper_autopilot_caps import (
    LIVE_OR_FILLED_STATUSES,
    new_entries_today,
    new_entries_this_hour,
    open_position_count,
)
from app.services.paper_trade_protections import (
    ProtectionResult,
    collect_protection_context,
    run_all_protections,
)


# Defaults are intentionally conservative; operator-tunable via
# ``autonomous_paper_learning.opportunity_budget.*`` (never disabled to "unlimited").
BUDGET_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "max_daily_risk_pct": 4.0,          # % of equity that may be at open risk + realized loss
    "max_open_risk_pct": 4.0,           # % of equity allowed in simultaneous open risk
    "min_edge_after_cost_bps": 15.0,    # minimum positive edge after round-trip cost
    "min_signal_score": 0.50,           # minimum normalized signal score [0..1]
    "default_trade_risk_pct": 1.0,      # assumed per-trade risk if none supplied
    # Safety circuit-breaker (NOT a strategy cap): generous ceiling on orders/day.
    "absolute_max_orders_per_day": 200,
    # Broker-health gating (mirrors the scheduler auto-pause thresholds).
    "max_broker_error_streak": 3,
    "max_rejection_streak": 3,
}


def budget_config(config: dict) -> dict[str, Any]:
    apl = (config or {}).get("autonomous_paper_learning") or {}
    raw = apl.get("opportunity_budget") or {}
    merged = dict(BUDGET_DEFAULTS)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if v is not None})
    return merged


def _num(v: Any, fallback: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else fallback
    except (TypeError, ValueError):
        return fallback


@dataclass
class BudgetInputs:
    symbol: str = ""
    equity: float = 0.0
    deployable_cash: float = 0.0
    open_positions: int = 0
    open_risk_usd: float = 0.0
    realized_pl_today: float = 0.0
    unrealized_pl: float = 0.0
    drawdown_pct: float = 0.0
    broker_error_streak: int = 0
    rejection_streak: int = 0
    reconciliation_ok: bool = True
    signal_score: Optional[float] = None
    edge_after_cost_bps: Optional[float] = None
    spread_pct: Optional[float] = None
    liquidity_ok: bool = True
    atr_pct: Optional[float] = None
    proposed_trade_risk_usd: Optional[float] = None
    orders_today: int = 0
    # telemetry only (no longer a blocker)
    entries_today: int = 0
    entries_this_hour: int = 0


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str
    score: float = 0.0
    risk_budget_used: float = 0.0
    risk_budget_remaining: float = 0.0
    edge_after_cost: Optional[float] = None
    warnings: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "score": round(self.score, 2),
            "risk_budget_used": round(self.risk_budget_used, 2),
            "risk_budget_remaining": round(self.risk_budget_remaining, 2),
            "edge_after_cost": self.edge_after_cost,
            "warnings": self.warnings,
            "evidence": self.evidence,
        }


def _composite_score(inp: BudgetInputs, edge: float, remaining: float, allowance: float) -> float:
    """0..100 quality score: blends signal strength, edge, and risk-budget headroom."""
    sig = max(0.0, min(1.0, _num(inp.signal_score, 0.5)))
    edge_norm = max(0.0, min(1.0, edge / 100.0)) if edge is not None else 0.0  # ~100bps -> full
    headroom = max(0.0, min(1.0, (remaining / allowance) if allowance > 0 else 0.0))
    return 100.0 * (0.45 * sig + 0.35 * edge_norm + 0.20 * headroom)


def evaluate_opportunity_budget(
    inp: BudgetInputs,
    config: dict,
    protection_result: Optional[ProtectionResult] = None,
) -> BudgetDecision:
    """Pure decision: should ONE more new entry be allowed right now?

    Order of checks (first failure wins): circuit-breaker → broker health →
    reconciliation → protections → weak edge → weak signal → risk budget."""
    cfg = budget_config(config)
    warnings: list[str] = list(getattr(protection_result, "warnings", []) or [])

    equity = max(0.0, _num(inp.equity))
    allowance = equity * _num(cfg["max_daily_risk_pct"], 4.0) / 100.0
    realized_loss = max(0.0, -_num(inp.realized_pl_today))
    used = max(0.0, _num(inp.open_risk_usd)) + realized_loss
    remaining = max(0.0, allowance - used)

    proposed_risk = inp.proposed_trade_risk_usd
    if proposed_risk is None:
        proposed_risk = equity * _num(cfg["default_trade_risk_pct"], 1.0) / 100.0
    proposed_risk = max(0.0, _num(proposed_risk))

    edge = _num(inp.edge_after_cost_bps) if inp.edge_after_cost_bps is not None else None
    score = _composite_score(inp, edge if edge is not None else 0.0, remaining, allowance)

    def decision(allowed: bool, reason: str, extra: Optional[dict] = None) -> BudgetDecision:
        return BudgetDecision(
            allowed=allowed,
            reason=reason,
            score=score,
            risk_budget_used=used,
            risk_budget_remaining=remaining,
            edge_after_cost=edge,
            warnings=warnings,
            evidence={
                "allowance_usd": round(allowance, 2),
                "proposed_trade_risk_usd": round(proposed_risk, 2),
                "entries_today": inp.entries_today,
                "open_positions": inp.open_positions,
                **(extra or {}),
            },
        )

    if not bool(cfg.get("enabled", True)):
        return decision(True, "opportunity_budget_disabled")

    # 1) Circuit-breaker (safety sanity bound, generous; not a strategy cap)
    ceiling = int(cfg["absolute_max_orders_per_day"])
    if ceiling > 0 and inp.orders_today >= ceiling:
        return decision(False, "CIRCUIT_BREAKER_MAX_ORDERS_PER_DAY", {"orders_today": inp.orders_today, "ceiling": ceiling})

    # 2) Broker health
    if inp.broker_error_streak >= int(cfg["max_broker_error_streak"]):
        return decision(False, "BROKER_ERROR_STREAK", {"broker_error_streak": inp.broker_error_streak})
    if inp.rejection_streak >= int(cfg["max_rejection_streak"]):
        return decision(False, "REJECTION_STREAK", {"rejection_streak": inp.rejection_streak})

    # 3) Reconciliation drift
    if not inp.reconciliation_ok:
        return decision(False, "RECONCILIATION_DRIFT")

    # 4) Deterministic protections (drawdown / stoploss / low-profit / cooldown / churn)
    if protection_result is not None and protection_result.blocked:
        warnings = list(protection_result.warnings)
        return decision(False, protection_result.code or "PROTECTION_BLOCKED", {"protection": protection_result.reason})

    # 5) Strategy quality — weak edge after cost
    min_edge = _num(cfg["min_edge_after_cost_bps"], 15.0)
    if edge is not None and edge < min_edge:
        return decision(False, "WEAK_EDGE_AFTER_COST", {"min_edge_after_cost_bps": min_edge})

    # 6) Weak signal
    if inp.signal_score is not None and _num(inp.signal_score) < _num(cfg["min_signal_score"], 0.5):
        return decision(False, "WEAK_SIGNAL", {"min_signal_score": cfg["min_signal_score"]})

    # 7) Liquidity
    if not inp.liquidity_ok:
        return decision(False, "LIQUIDITY_FAILED")

    # 8) Risk budget exhausted
    if proposed_risk > remaining:
        return decision(False, "RISK_BUDGET_EXHAUSTED", {"need_usd": round(proposed_risk, 2)})

    return decision(True, "ok")


# ─────────────────────────────────────────────────────────────────────────
# DB / account collection (defensive)
# ─────────────────────────────────────────────────────────────────────────
def _orders_today(session: Session) -> int:
    try:
        since = datetime.utcnow() - timedelta(days=1)
        rows = session.exec(
            select(ExecutionLog).where(
                ExecutionLog.submitted_at >= since,
                ExecutionLog.status.in_(LIVE_OR_FILLED_STATUSES),
            )
        ).all()
        return len(list(rows))
    except Exception:
        return 0


def _estimate_open_risk(positions: list, equity: float, config: dict) -> float:
    """Sum (entry-stop)*qty across positions when available; else fall back to a
    fraction of position notional. Defensive — never raises."""
    total = 0.0
    cfg = budget_config(config)
    fallback_pct = _num(cfg["default_trade_risk_pct"], 1.0) / 100.0
    for p in positions or []:
        try:
            g = (lambda k: p.get(k) if isinstance(p, dict) else getattr(p, k, None))
            qty = _num(g("qty"))
            entry = _num(g("avg_entry") or g("avg_entry_price") or g("entry_price"))
            stop = _num(g("stop_loss") or g("stop"))
            mark = _num(g("current_price") or g("mark") or entry)
            if qty > 0 and entry > 0 and 0 < stop < entry:
                total += (entry - stop) * qty
            elif qty > 0 and mark > 0:
                total += mark * qty * fallback_pct
        except Exception:
            continue
    return total


def collect_budget_inputs(
    session: Session,
    config: dict,
    *,
    symbol: str,
    account: Any = None,
    positions: Optional[list] = None,
    signal_score: Optional[float] = None,
    edge_after_cost_bps: Optional[float] = None,
    spread_pct: Optional[float] = None,
    atr_pct: Optional[float] = None,
    proposed_trade_risk_usd: Optional[float] = None,
    broker_error_streak: int = 0,
    rejection_streak: int = 0,
    reconciliation_ok: bool = True,
) -> BudgetInputs:
    positions = positions or []
    equity = _num(getattr(account, "equity", None)) if account is not None else 0.0
    cash = _num(getattr(account, "cash", None)) if account is not None else 0.0
    drawdown = abs(_num(getattr(account, "drawdown_pct", None))) if account is not None else 0.0
    unrealized = _num(getattr(account, "unrealized_pl", None)) if account is not None else 0.0
    # AccountSnapshot exposes daily_pl (not realized_pl_today). Use an explicit realized
    # field when present, else fall back to daily_pl, so today's losses tighten the budget.
    if account is not None:
        _today_pl = getattr(account, "realized_pl_today", None)
        if _today_pl is None:
            _today_pl = getattr(account, "daily_pl", None)
        realized_today = _num(_today_pl)
    else:
        realized_today = 0.0

    return BudgetInputs(
        symbol=symbol,
        equity=equity,
        deployable_cash=cash,
        open_positions=len([p for p in positions if _num(p.get("qty") if isinstance(p, dict) else getattr(p, "qty", 0)) > 0]) or open_position_count(session),
        open_risk_usd=_estimate_open_risk(positions, equity, config),
        realized_pl_today=realized_today,
        unrealized_pl=unrealized,
        drawdown_pct=drawdown,
        broker_error_streak=int(broker_error_streak or 0),
        rejection_streak=int(rejection_streak or 0),
        reconciliation_ok=bool(reconciliation_ok),
        signal_score=signal_score,
        edge_after_cost_bps=edge_after_cost_bps,
        spread_pct=spread_pct,
        atr_pct=atr_pct,
        proposed_trade_risk_usd=proposed_trade_risk_usd,
        orders_today=_orders_today(session),
        entries_today=new_entries_today(session),
        entries_this_hour=new_entries_this_hour(session),
    )


def decide_entry(
    session: Session,
    config: dict,
    *,
    symbol: str,
    account: Any = None,
    positions: Optional[list] = None,
    signal_score: Optional[float] = None,
    edge_after_cost_bps: Optional[float] = None,
    spread_pct: Optional[float] = None,
    atr_pct: Optional[float] = None,
    proposed_trade_risk_usd: Optional[float] = None,
    broker_error_streak: int = 0,
    rejection_streak: int = 0,
    reconciliation_ok: bool = True,
    setup: Optional[str] = None,
) -> BudgetDecision:
    """Collect inputs + run protections + evaluate the budget. Convenience entry point
    for the execution cage. Read-only."""
    inp = collect_budget_inputs(
        session,
        config,
        symbol=symbol,
        account=account,
        positions=positions,
        signal_score=signal_score,
        edge_after_cost_bps=edge_after_cost_bps,
        spread_pct=spread_pct,
        atr_pct=atr_pct,
        proposed_trade_risk_usd=proposed_trade_risk_usd,
        broker_error_streak=broker_error_streak,
        rejection_streak=rejection_streak,
        reconciliation_ok=reconciliation_ok,
    )
    try:
        pctx = collect_protection_context(
            session,
            config,
            symbol=symbol,
            drawdown_pct=inp.drawdown_pct,
            signal_score=signal_score,
            edge_after_cost_bps=edge_after_cost_bps,
            setup=setup,
        )
        protection_result = run_all_protections(pctx, config)
    except Exception as exc:  # fail-open: protections never crash the cage
        protection_result = ProtectionResult(warnings=[f"protections_error:{type(exc).__name__}"])
    return evaluate_opportunity_budget(inp, config, protection_result)
