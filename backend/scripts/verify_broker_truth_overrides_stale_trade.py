"""Broker-flat truth overrides stale local open TradeRecord rows.

This proves the duplicate-buy gate treats local open trades as evidence when
broker truth is available and flat, not as a hard duplicate-position blocker.
"""

from __future__ import annotations

import copy
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import AccountSnapshot, PortfolioDecision, TradeRecord
from app.services.default_config import DEFAULT_CONFIG
from app.services.execution_preflight import run_preflight
from app.services.exposure_truth_service import ExposureTruthService
from app.services.portfolio_gate import ApprovedCandidate


def _session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _cfg() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.setdefault("execution", {})["paper_orders_enabled"] = True
    cfg.setdefault("autonomous_paper_learning", {})["no_duplicate_symbol_buy"] = True
    cfg["autonomous_paper_learning"]["no_averaging_down"] = True
    return cfg


def _candidate(symbol: str) -> ApprovedCandidate:
    return ApprovedCandidate(
        signal_id=1,
        symbol=symbol,
        side="buy",
        signal_type="entry",
        meta={"expected_hold_time": "12h"},
        strength=1.0,
        confidence=0.9,
        spread_pct=0.001,
        liquidity_score=90,
        edge_over_cost=3,
        expected_move_pct=2,
        position_qty=1,
        entry_price=100,
        stop_loss=95,
        atr14=1,
        tier="TIER_MAJOR",
        cost_evidence={},
        sizing_evidence={},
    )


def main() -> None:
    session = _session()
    symbol = "DOGE/USD"
    session.add(AccountSnapshot(equity=200, cash=200, buying_power=200, portfolio_value=200))
    session.add(
        TradeRecord(
            symbol=symbol,
            strategy="fixture",
            side="buy",
            entry_price=0.10,
            quantity=100,
            status="open",
            opened_at=datetime.utcnow(),
        )
    )
    session.commit()

    dupe = ExposureTruthService(session, _cfg()).duplicate_buy_decision(
        symbol,
        broker_positions=[],
        broker_truth_available=True,
    )
    assert dupe["blocked"] is False, dupe
    assert dupe["effective_exposure_state"] == "broker_flat_local_stale", dupe
    assert dupe["allowed_reason"] == "broker_flat_overrides_stale_local_open", dupe

    pd = PortfolioDecision(
        id=1,
        cycle_run_id="cycle",
        signal_id=1,
        symbol=symbol,
        side="buy",
        signal_type="entry",
        portfolio_status="portfolio_approved",
        selected_for_execution=True,
        portfolio_rank=1,
    )
    res = run_preflight(
        session,
        _cfg(),
        cand=_candidate(symbol),
        cycle_run_id="cycle",
        portfolio_decision=pd,
        account=type("A", (), {"equity": 200, "cash": 200, "buying_power": 200, "daily_pl_pct": 0, "drawdown_pct": 0})(),
        positions=[],
        open_order_symbols=set(),
        alpaca=type("B", (), {"broker_sync_rate_limited": False})(),
        quote={"bid": 99, "ask": 101, "mid": 100, "spread_pct": 0.001},
        signal_row=type("S", (), {"stop_loss": 95, "take_profit": 110, "signal_metadata": {}, "status": "risk_approved"})(),
    )
    assert res.block_reason_code != "DUPLICATE_SYMBOL_POSITION", res.to_dict()
    print("verify_broker_truth_overrides_stale_trade: PASS")
    print({"symbol": symbol, "state": dupe["effective_exposure_state"], "preflight_code": res.block_reason_code})


if __name__ == "__main__":
    main()
