"""Churn / fee-negative entry-quality guards (symbol + setup + losing streak).

Proves:
- repeated fee-negative exits on a symbol create a cooldown (entry blocked)
- a setup/strategy that is net-negative across symbols is cooled down even when no single
  symbol has enough trades
- weak entries are blocked by the adaptive budget; a strong edge+signal is still allowed
- entry-quality diagnostics are surfaced
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import PaperExperimentOutcome
from app.services.adaptive_opportunity_budget import BudgetInputs, evaluate_opportunity_budget
from app.services.paper_trade_protections import collect_protection_context, run_all_protections

CFG: dict = {}
_BLOCK_CODES = {
    "LOW_PROFIT_SYMBOL_COOLDOWN",
    "LOW_PROFIT_SETUP_COOLDOWN",
    "LOSING_STREAK_COOLDOWN",
    "CHURN_GUARD",
    "COOLDOWN_AFTER_EXIT",
}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_repeated_fee_negative_symbol_cooldown() -> None:
    s = _mem()
    for _ in range(4):
        s.add(PaperExperimentOutcome(strategy_id="crypto_push_pull", symbol="DOGE/USD", realized_pnl=0.0, fees_estimated=0.3, exit_reason="time_stop"))
    s.commit()
    ctx = collect_protection_context(s, CFG, symbol="DOGE/USD", setup="crypto_push_pull", edge_after_cost_bps=10.0)
    res = run_all_protections(ctx, CFG)
    assert res.blocked and res.code in _BLOCK_CODES, res
    assert "entry_quality_block_reason" in res.evidence and "recent_symbol_pnl_after_fees" in res.evidence, res.evidence
    s.close()
    print(f"churn-guard: 4 fee-negative DOGE exits -> entry blocked [{res.code}] + diagnostics — PASS")


def test_setup_level_cooldown_across_symbols() -> None:
    s = _mem()
    for sym in ("A/USD", "B/USD", "C/USD", "D/USD"):
        s.add(PaperExperimentOutcome(strategy_id="setupX", symbol=sym, realized_pnl=-0.5, fees_estimated=0.1, exit_reason="time_stop"))
    s.commit()
    # Symbol E has no trades, but setupX is net-negative over 4 trades -> setup cooldown.
    ctx = collect_protection_context(s, CFG, symbol="E/USD", setup="setupX", edge_after_cost_bps=100.0)
    res = run_all_protections(ctx, CFG)
    assert res.blocked and res.code in ("LOW_PROFIT_SETUP_COOLDOWN", "LOSING_STREAK_COOLDOWN"), res
    s.close()
    print(f"churn-guard: net-negative setupX cools the whole setup [{res.code}] — PASS")


def test_weak_entry_blocked_strong_allowed() -> None:
    weak_sig = evaluate_opportunity_budget(BudgetInputs(symbol="SOL/USD", equity=1000.0, signal_score=0.20, edge_after_cost_bps=50.0), CFG)
    assert not weak_sig.allowed and weak_sig.reason == "WEAK_SIGNAL", weak_sig
    weak_edge = evaluate_opportunity_budget(BudgetInputs(symbol="SOL/USD", equity=1000.0, signal_score=0.85, edge_after_cost_bps=5.0), CFG)
    assert not weak_edge.allowed and weak_edge.reason == "WEAK_EDGE_AFTER_COST", weak_edge
    strong = evaluate_opportunity_budget(
        BudgetInputs(symbol="SOL/USD", equity=1000.0, signal_score=0.85, edge_after_cost_bps=60.0, entries_today=99), CFG
    )
    assert strong.allowed and strong.reason == "ok", strong
    print("churn-guard: weak signal/edge blocked; strong edge+signal still allowed — PASS")


if __name__ == "__main__":
    test_repeated_fee_negative_symbol_cooldown()
    test_setup_level_cooldown_across_symbols()
    test_weak_entry_blocked_strong_allowed()
    print("ALL PASS: verify_churn_and_fee_negative_guard")
