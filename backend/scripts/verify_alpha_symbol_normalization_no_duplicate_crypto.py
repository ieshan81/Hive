"""ETHUSD and ETH/USD map to one scorecard identity; crypto pairs are asset_class=crypto."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.database  # noqa: F401
from app.database import AlphaScorecard, ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

CFG = {"alpha_factory": {"min_sample_size": 5}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_compact_and_slash_dedupe_to_one_crypto_scorecard() -> None:
    s = _mem()
    # Same asset, two formats, same strategy/timeframe -> must collapse to ONE scorecard.
    s.add(ResearchBacktestRun(run_id="a", strategy_id="crypto_push_pull_momentum", symbols=["ETH/USD"],
                              status="completed", num_trades=10, sample_size=10, source="autonomous_research_worker",
                              metrics_json={"expectancy": -0.01, "profit_factor": 0.8, "max_drawdown_pct": 5.0}))
    s.add(ResearchBacktestRun(run_id="b", strategy_id="crypto_push_pull_momentum", symbols=["ETHUSD"],
                              status="completed", num_trades=12, sample_size=12, source="autonomous_research_worker",
                              metrics_json={"expectancy": -0.008, "profit_factor": 0.9, "max_drawdown_pct": 5.0}))
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    eth = list(s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == "ETHUSD")).all())
    assert len(eth) == 1, f"expected 1 ETH scorecard, got {len(eth)}"
    assert eth[0].asset_class == "crypto", f"ETH compact misclassified: {eth[0].asset_class}"
    print("symbol-norm: ETH/USD + ETHUSD -> 1 scorecard, asset_class=crypto — PASS")


def test_compact_crypto_not_stock() -> None:
    s = _mem()
    for rid, sym in (("c1", "BTCUSD"), ("c2", "SOLUSD"), ("c3", "DOGEUSD")):
        s.add(ResearchBacktestRun(run_id=rid, strategy_id="crypto_push_pull_baseline", symbols=[sym],
                                  status="completed", num_trades=8, sample_size=8, source="autonomous_research_worker",
                                  metrics_json={"expectancy": -0.01, "profit_factor": 0.7, "max_drawdown_pct": 5.0}))
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    for norm in ("BTCUSD", "SOLUSD", "DOGEUSD"):
        sc = s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == norm)).first()
        assert sc and sc.asset_class == "crypto", (norm, sc.asset_class if sc else None)
    s.close()
    print("symbol-norm: compact crypto (BTCUSD/SOLUSD/DOGEUSD) classified crypto, not stock — PASS")


if __name__ == "__main__":
    test_compact_and_slash_dedupe_to_one_crypto_scorecard()
    test_compact_crypto_not_stock()
    print("ALL PASS: verify_alpha_symbol_normalization_no_duplicate_crypto")
