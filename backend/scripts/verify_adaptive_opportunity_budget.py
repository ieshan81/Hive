"""Adaptive opportunity budget allows/blocks ONE new entry on risk-based criteria.

Proves the decision matrix of app.services.adaptive_opportunity_budget:
- strong signal + good edge + healthy account → allowed
- weak edge / weak signal → blocked
- broker error streak / rejection streak → blocked
- reconciliation drift → blocked
- risk budget exhausted → blocked
- circuit-breaker (orders/day) → blocked
- deterministic protections (drawdown, low-profit symbol) → blocked
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import PaperExperimentOutcome
from app.services.adaptive_opportunity_budget import BudgetInputs, evaluate_opportunity_budget
from app.services.paper_trade_protections import (
    ProtectionContext,
    collect_protection_context,
    run_all_protections,
)

CFG: dict = {}


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _inp(**kw) -> BudgetInputs:
    base = dict(symbol="SOL/USD", equity=1000.0, signal_score=0.80, edge_after_cost_bps=50.0)
    base.update(kw)
    return BudgetInputs(**base)


def test_strong_allowed() -> None:
    d = evaluate_opportunity_budget(_inp(entries_today=15, orders_today=20), CFG)
    assert d.allowed and d.reason == "ok", d
    assert d.score > 0, d
    print("budget: strong signal+edge allowed (entries_today=15 > retired 6 cap) — PASS")


def test_weak_edge_blocked() -> None:
    d = evaluate_opportunity_budget(_inp(edge_after_cost_bps=5.0), CFG)
    assert not d.allowed and d.reason == "WEAK_EDGE_AFTER_COST", d
    print("budget: weak edge after cost blocked — PASS")


def test_weak_signal_blocked() -> None:
    d = evaluate_opportunity_budget(_inp(signal_score=0.20), CFG)
    assert not d.allowed and d.reason == "WEAK_SIGNAL", d
    print("budget: weak signal blocked — PASS")


def test_broker_error_blocked() -> None:
    d = evaluate_opportunity_budget(_inp(broker_error_streak=3), CFG)
    assert not d.allowed and d.reason == "BROKER_ERROR_STREAK", d
    print("budget: broker error streak blocked — PASS")


def test_rejection_blocked() -> None:
    d = evaluate_opportunity_budget(_inp(rejection_streak=3), CFG)
    assert not d.allowed and d.reason == "REJECTION_STREAK", d
    print("budget: rejection streak blocked — PASS")


def test_reconciliation_blocked() -> None:
    d = evaluate_opportunity_budget(_inp(reconciliation_ok=False), CFG)
    assert not d.allowed and d.reason == "RECONCILIATION_DRIFT", d
    print("budget: reconciliation drift blocked — PASS")


def test_circuit_breaker_blocked() -> None:
    d = evaluate_opportunity_budget(_inp(orders_today=200), CFG)
    assert not d.allowed and d.reason == "CIRCUIT_BREAKER_MAX_ORDERS_PER_DAY", d
    print("budget: orders/day circuit-breaker blocked — PASS")


def test_risk_budget_exhausted() -> None:
    # equity 100 → daily allowance 4% = $4; a $50 proposed risk cannot fit.
    d = evaluate_opportunity_budget(_inp(equity=100.0, proposed_trade_risk_usd=50.0), CFG)
    assert not d.allowed and d.reason == "RISK_BUDGET_EXHAUSTED", d
    print("budget: risk budget exhausted blocked — PASS")


def test_drawdown_protection_blocked() -> None:
    pr = run_all_protections(ProtectionContext(symbol="SOL/USD", drawdown_pct=15.0), CFG)
    d = evaluate_opportunity_budget(_inp(), CFG, pr)
    assert not d.allowed and d.reason == "MAX_DRAWDOWN_PROTECTION", d
    print("budget: max-drawdown protection blocked — PASS")


def test_low_profit_symbol_blocked() -> None:
    ctx = ProtectionContext(symbol="SOL/USD", symbol_net_pnl_usd=-5.0, symbol_trade_count=4)
    pr = run_all_protections(ctx, CFG)
    d = evaluate_opportunity_budget(_inp(), CFG, pr)
    assert not d.allowed and d.reason == "LOW_PROFIT_SYMBOL_COOLDOWN", d
    print("budget: low-profit symbol cooldown blocked — PASS")


def test_collector_reads_real_outcomes_not_execlog() -> None:
    """Regression for Codex review: protections read PaperExperimentOutcome (which has
    realized PnL / exit_reason), not ExecutionLog. With no outcomes, churn/low-profit
    must NOT fire; profitable exits must NOT be counted flat; real fee-negative ones do."""
    session = _mem_session()
    # 1) Empty -> no flat/low-profit, no spurious block.
    c0 = collect_protection_context(session, CFG, symbol="SOL/USD")
    assert c0.recent_flat_trades == 0 and c0.symbol_trade_count == 0, c0
    assert run_all_protections(c0, CFG).code not in ("CHURN_GUARD", "LOW_PROFIT_SYMBOL_COOLDOWN"), c0

    # 2) Profitable exits -> positive net, zero flat, NOT churn/low-profit blocked.
    for _ in range(4):
        session.add(PaperExperimentOutcome(strategy_id="x", symbol="SOL/USD", realized_pnl=2.0, fees_estimated=0.2, exit_reason="take_profit"))
    session.commit()
    c1 = collect_protection_context(session, CFG, symbol="SOL/USD")
    assert c1.recent_flat_trades == 0 and c1.symbol_net_pnl_usd > 0, c1
    assert run_all_protections(c1, CFG).code not in ("CHURN_GUARD", "LOW_PROFIT_SYMBOL_COOLDOWN"), c1

    # 3) Real fee-negative exits -> counted flat, guard fires.
    for _ in range(4):
        session.add(PaperExperimentOutcome(strategy_id="x", symbol="DOGE/USD", realized_pnl=0.0, fees_estimated=0.3, exit_reason="time"))
    session.commit()
    c2 = collect_protection_context(session, CFG, symbol="DOGE/USD")
    assert c2.recent_flat_trades >= 4 and run_all_protections(c2, CFG).blocked, c2
    session.close()
    print("budget: protections read real outcomes (no false churn on empty/profitable) — PASS")


if __name__ == "__main__":
    test_collector_reads_real_outcomes_not_execlog()
    test_strong_allowed()
    test_weak_edge_blocked()
    test_weak_signal_blocked()
    test_broker_error_blocked()
    test_rejection_blocked()
    test_reconciliation_blocked()
    test_circuit_breaker_blocked()
    test_risk_budget_exhausted()
    test_drawdown_protection_blocked()
    test_low_profit_symbol_blocked()
    print("ALL PASS: verify_adaptive_opportunity_budget")
