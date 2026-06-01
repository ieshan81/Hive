"""Unified autonomous status never says never_run when legacy research has run."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import ResearchBacktestRun
from app.services.alpha_research_read_model_service import AlphaResearchReadModelService

CFG = {"alpha_factory": {"min_sample_size": 5}}
REQUIRED = (
    "enabled", "alpha_factory_enabled", "old_research_enabled", "legacy_research_detected",
    "last_research_at", "last_alpha_cycle_at", "last_backtest_at", "last_walk_forward_at",
    "last_alpha_scorecard_write_at", "scorecards_written", "memory_written", "skipped_reason",
    "plain_english",
)


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_unified_status_fields_and_legacy() -> None:
    s = _mem()
    st0 = AlphaResearchReadModelService(s, CFG).get_unified_autonomous_alpha_status()
    for k in REQUIRED:
        assert k in st0, f"missing field {k}"
    assert st0["orders_authority"] == "none", st0

    # With a legacy research run present, status must acknowledge legacy (not "never_run").
    s.add(ResearchBacktestRun(run_id="lg", strategy_id="crypto_push_pull", symbols=["BTC/USD"],
                              status="completed", num_trades=8, sample_size=8, source="autonomous_research_worker",
                              metrics_json={"expectancy": 0.0, "profit_factor": 1.0}))
    s.commit()
    st1 = AlphaResearchReadModelService(s, CFG).get_unified_autonomous_alpha_status()
    assert st1["legacy_research_detected"] is True, st1
    assert st1["last_research_at"] is not None, st1
    assert "never_run" not in (st1["plain_english"] or "").lower(), st1
    assert "legacy" in (st1["plain_english"] or "").lower(), st1
    s.close()
    print(f"unified-status: all fields present; legacy acknowledged -> '{st1['plain_english']}' — PASS")


if __name__ == "__main__":
    test_unified_status_fields_and_legacy()
    print("ALL PASS: verify_alpha_scheduler_unified_status")
