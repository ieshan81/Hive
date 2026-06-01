"""Scorecards consolidate into ONE durable alpha memory each (not raw event spam).

Proves: every scorecard -> one consolidated LessonNode; re-running is idempotent (no
duplicates, occurrence_count grows); a verdict change supersedes the prior memory so only
one active lesson per (strategy, symbol, timeframe) pattern remains.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.database  # noqa: F401
from app.database import AlphaScorecard, LessonNode, ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.memory_evidence_consolidator_v2 import MemoryEvidenceConsolidatorV2

CFG = {"alpha_factory": {"min_sample_size": 5}}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _run(s, rid, strat, sym, *, sample, exp, pf, dd):
    s.add(ResearchBacktestRun(run_id=rid, strategy_id=strat, symbols=[sym], status="completed",
                              num_trades=sample, sample_size=sample, source="autonomous_research_worker",
                              metrics_json={"win_rate": 0.55, "expectancy": exp, "profit_factor": pf, "max_drawdown_pct": dd}))


def _active(s):
    return list(s.exec(select(LessonNode).where(LessonNode.status == "active")).all())


def test_scorecards_create_consolidated_memory() -> None:
    s = _mem()
    _run(s, "eth", "crypto_push_pull_baseline", "ETH/USD", sample=30, exp=0.012, pf=1.8, dd=4.0)  # paper_candidate
    _run(s, "uni", "crypto_push_pull_momentum", "UNI/USD", sample=26, exp=-0.02, pf=0.5, dd=9.0)  # rejected
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()

    cons = MemoryEvidenceConsolidatorV2(s, CFG)
    out1 = cons.consolidate_scorecards()
    s.commit()
    assert out1["scorecards_seen"] == 2, out1
    assert out1["memory_written_count"] == 2, out1
    assert out1["raw_events_hidden"] is True, out1

    active = _active(s)
    assert len(active) == 2, f"expected 2 consolidated memories, got {len(active)}"
    for m in active:
        assert m.is_consolidated is True, m.title
        assert m.memory_level == "consolidated_lesson", m.memory_level
        assert m.related_entity_type == "alpha_scorecard"
    types = {m.memory_type for m in active}
    assert "validated_alpha_candidate" in types, types     # ETH paper_candidate
    assert "rejected_alpha_candidate" in types, types       # UNI rejected

    # Idempotent: re-run writes 0 NEW rows, occurrence_count increments, still 2 active.
    before_occ = sum(m.occurrence_count for m in active)
    out2 = cons.consolidate_scorecards()
    s.commit()
    assert out2["memory_written_count"] == 0, out2
    active2 = _active(s)
    assert len(active2) == 2, f"duplicates created on re-run: {len(active2)}"
    assert sum(m.occurrence_count for m in active2) > before_occ, "occurrence_count did not grow"

    # Verdict change supersedes prior memory (one active per pattern).
    eth = s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == "ETHUSD")).first()
    eth.verdict = "rejected"
    s.add(eth)
    s.commit()
    cons.consolidate_scorecards()
    s.commit()
    eth_active = [m for m in _active(s) if m.symbol == "ETH/USD"]
    assert len(eth_active) == 1, f"expected 1 active ETH memory after supersede, got {len(eth_active)}"
    # Verdict superseded in place on the stable pattern_key (no duplicate, no stale verdict).
    assert eth_active[0].memory_type == "rejected_alpha_candidate", eth_active[0].memory_type
    assert eth_active[0].can_influence_ranking is False, "rejected memory must not influence ranking"
    assert len(_active(s)) == 2, "supersede must not change the active memory count"
    s.close()
    print("scorecard-memory: 2 scorecards -> 2 consolidated lessons; idempotent; verdict supersedes — PASS")


if __name__ == "__main__":
    test_scorecards_create_consolidated_memory()
    print("ALL PASS: verify_scorecards_create_consolidated_alpha_memory")
