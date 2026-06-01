"""Alpha Factory bootstrap/cycle never creates broker orders (research-only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

import app.database  # noqa: F401
from app.database import ExecutionLog, OrderRecord, ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

CFG = {"alpha_factory": {"min_sample_size": 5}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _orders(s) -> int:
    return int(s.exec(select(func.count()).select_from(OrderRecord)).one() or 0) + int(
        s.exec(select(func.count()).select_from(ExecutionLog)).one() or 0
    )


def test_no_orders_from_bootstrap() -> None:
    s = _mem()
    s.add(ResearchBacktestRun(run_id="r1", strategy_id="crypto_push_pull_baseline", symbols=["ETH/USD"],
                              status="completed", num_trades=20, sample_size=20, source="autonomous_research_worker",
                              metrics_json={"win_rate": 0.6, "expectancy": 0.01, "profit_factor": 1.6, "max_drawdown_pct": 5.0}))
    s.commit()
    before = _orders(s)
    out = AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    after = _orders(s)
    assert out["orders_created"] == 0, out
    assert after == before == 0, (before, after)
    s.close()
    print("no-orders: bootstrap wrote scorecards but created 0 broker orders/execution logs — PASS")


if __name__ == "__main__":
    test_no_orders_from_bootstrap()
    print("ALL PASS: verify_alpha_factory_run_cycle_never_places_orders")
