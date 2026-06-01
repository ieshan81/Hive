"""Research rotates away from repeatedly insufficient-sample symbols.

A symbol whose recent research keeps returning too-few trades is pushed to the back of the
research queue so fresh setups get studied first — instead of re-churning the same thin one.
This never promotes or trades; it only reorders/deduplicates research targets.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import ResearchBacktestRun
from app.services.autonomous_strategy_generator import AutonomousStrategyGenerator

CFG = {"alpha_factory": {"min_sample_size": 5}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _run(s, rid, sym, sample):
    s.add(ResearchBacktestRun(run_id=rid, strategy_id="crypto_push_pull_baseline", symbols=[sym],
                              status="completed", num_trades=sample, sample_size=sample,
                              source="autonomous_research_worker", metrics_json={"expectancy": 0.0}))


def test_thin_symbol_rotates_to_back() -> None:
    s = _mem()
    # THIN/USD: 3 recent runs all insufficient sample (1,2,1). FRESH/USD: one healthy run.
    _run(s, "t1", "THIN/USD", 1)
    _run(s, "t2", "THIN/USD", 2)
    _run(s, "t3", "THIN/USD", 1)
    _run(s, "f1", "FRESH/USD", 30)
    s.commit()
    gen = AutonomousStrategyGenerator(s, CFG)

    thin = gen._repeatedly_thin_symbols()
    assert "THINUSD" in thin, thin
    assert "FRESHUSD" not in thin, thin

    # When the queue can only take 1 symbol, the thin one is rotated out in favor of the fresh one.
    picked_one = gen._symbols(None, limit=1)
    assert picked_one == ["FRESH/USD"], picked_one

    # With room for both, the thin symbol still ranks AFTER the fresh one.
    picked_all = gen._symbols(None, limit=10)
    assert picked_all.index("FRESH/USD") < picked_all.index("THIN/USD"), picked_all
    # No duplicates introduced by rotation.
    assert len(picked_all) == len(set(picked_all)), picked_all
    s.close()
    print(f"research-rotation: thin={sorted(thin)}; queue order={picked_all} (fresh before thin) — PASS")


def test_longer_horizon_family_limited_to_majors() -> None:
    s = _mem()
    gen = AutonomousStrategyGenerator(s, CFG)
    cands = gen.generate(symbols=["BTC/USD", "PEPE/USD"], limit=10)
    lh_btc = [c for c in cands if c["strategy_family"] == "higher_timeframe_momentum" and c["symbol"] == "BTC/USD"]
    lh_pepe = [c for c in cands if c["strategy_family"] == "higher_timeframe_momentum" and c["symbol"] == "PEPE/USD"]
    assert lh_btc, "longer-horizon family must run on majors (BTC)"
    assert not lh_pepe, "longer-horizon family must NOT run on non-major (PEPE)"
    s.close()
    print("longer-horizon: higher_timeframe_momentum limited to approved majors — PASS")


if __name__ == "__main__":
    test_thin_symbol_rotates_to_back()
    test_longer_horizon_family_limited_to_majors()
    print("ALL PASS: verify_research_rotates_after_repeated_insufficient_sample")
