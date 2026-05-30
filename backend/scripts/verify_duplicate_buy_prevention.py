"""Duplicate-buy / averaging-down prevention (entries only; sells/exits allowed).

Proves, through the real ``run_preflight`` gate:
- holding a symbol blocks a NEW buy for it (DUPLICATE_SYMBOL_POSITION) — DOGE & SOL
- a recent live/working buy order blocks a re-buy (DUPLICATE_RECENT_ORDER)
- a sell/exit for a held symbol is NOT blocked by either duplicate gate
"""

import copy
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.database import ExecutionLog, PortfolioDecision
from app.services.default_config import DEFAULT_CONFIG
from app.services.execution_preflight import run_preflight
from app.services.portfolio_gate import ApprovedCandidate

_DUPE_CODES = ("DUPLICATE_SYMBOL_POSITION", "DUPLICATE_RECENT_ORDER")


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _cfg() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.setdefault("execution", {})["paper_orders_enabled"] = True
    return cfg


def _cand(**kw) -> ApprovedCandidate:
    base = dict(
        signal_id=1,
        symbol="BTC/USD",
        side="buy",
        signal_type="entry",
        meta={"expected_hold_time": "12h"},
        strength=1,
        confidence=0.9,
        spread_pct=0.001,
        liquidity_score=80,
        edge_over_cost=3,
        expected_move_pct=2.0,
        position_qty=0.05,
        entry_price=100,
        stop_loss=95,
        atr14=1,
        tier="TIER_MAJOR",
        cost_evidence={},
        sizing_evidence={},
    )
    base.update(kw)
    return ApprovedCandidate(**base)


def _pd(symbol: str, *, side: str = "buy", signal_type: str = "entry") -> PortfolioDecision:
    return PortfolioDecision(
        id=1,
        cycle_run_id="x",
        signal_id=1,
        symbol=symbol,
        side=side,
        signal_type=signal_type,
        portfolio_status="portfolio_approved",
        selected_for_execution=True,
        portfolio_rank=1,
    )


def _run(session, cfg, cand, pd, positions):
    return run_preflight(
        session,
        cfg,
        cand=cand,
        cycle_run_id="x",
        portfolio_decision=pd,
        account=type("A", (), {"equity": 200, "cash": 120, "buying_power": 200, "daily_pl_pct": 0, "drawdown_pct": 0})(),
        positions=positions,
        open_order_symbols=set(),
        alpaca=None,
        quote={"bid": 99, "ask": 101, "mid": 100, "spread_pct": 0.001},
        signal_row=type("S", (), {"stop_loss": 95, "take_profit": 110, "signal_metadata": {}, "status": "risk_approved"})(),
    )


def test_holding_blocks_new_buy() -> None:
    session = _mem_session()
    cfg = _cfg()
    for sym in ("DOGE/USD", "SOL/USD"):
        r = _run(session, cfg, _cand(symbol=sym), _pd(sym), positions=[{"symbol": sym, "qty": 100}])
        assert r.block_reason_code == "DUPLICATE_SYMBOL_POSITION", (sym, r.block_reason_code)
    session.close()
    print("dupe-buy: holding DOGE/SOL blocks a new buy — PASS")


def test_recent_order_blocks_rebuy() -> None:
    session = _mem_session()
    cfg = _cfg()
    # A recent live/working buy for ETH/USD (different signal_id so it does NOT
    # trip the earlier DUPLICATE_CLIENT_ORDER_ID / already-submitted gate).
    session.add(
        ExecutionLog(
            event_id="recent1",
            cycle_run_id="other",
            symbol="ETH/USD",
            side="buy",
            status="paper_order_submitted",
            submitted_at=datetime.utcnow(),
            signal_id=None,
        )
    )
    session.commit()
    r = _run(session, cfg, _cand(symbol="ETH/USD"), _pd("ETH/USD"), positions=[])
    assert r.block_reason_code == "DUPLICATE_RECENT_ORDER", r.block_reason_code
    session.close()
    print("dupe-buy: recent buy order blocks a re-buy — PASS")


def test_sell_exit_allowed_while_holding() -> None:
    session = _mem_session()
    cfg = _cfg()
    r = _run(
        session,
        cfg,
        _cand(symbol="DOGE/USD", side="sell", signal_type="exit"),
        _pd("DOGE/USD", side="sell", signal_type="exit"),
        positions=[{"symbol": "DOGE/USD", "qty": 100}],
    )
    assert r.block_reason_code not in _DUPE_CODES, r.block_reason_code
    session.close()
    print("dupe-buy: sell/exit still allowed while holding — PASS")


if __name__ == "__main__":
    test_holding_blocks_new_buy()
    test_recent_order_blocks_rebuy()
    test_sell_exit_allowed_while_holding()
    print("ALL PASS: verify_duplicate_buy_prevention")
