"""Promotion stays strict: paper_candidate only with full evidence; weak/zero/negative never."""

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


def _run(s, rid, strat, sym, *, sample, exp, pf, dd, win=0.5):
    s.add(ResearchBacktestRun(run_id=rid, strategy_id=strat, symbols=[sym], status="completed",
                              num_trades=sample, sample_size=sample, source="autonomous_research_worker",
                              metrics_json={"win_rate": win, "expectancy": exp, "profit_factor": pf, "max_drawdown_pct": dd}))


def _card(s, norm):
    return s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == norm)).first()


def test_full_evidence_promotes_others_do_not() -> None:
    s = _mem()
    _run(s, "good", "crypto_push_pull_baseline", "ETH/USD", sample=30, exp=0.012, pf=1.8, dd=4.0, win=0.6)   # full evidence
    _run(s, "neg", "crypto_push_pull_momentum", "AVAX/USD", sample=30, exp=-0.02, pf=0.5, dd=9.0)            # negative
    _run(s, "zero", "crypto_push_pull_baseline", "DOGE/USD", sample=0, exp=0.0, pf=0.0, dd=0.0)              # zero sample
    _run(s, "thin", "crypto_push_pull_baseline", "LINK/USD", sample=2, exp=0.01, pf=1.5, dd=3.0)             # insufficient
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    paper_allowed = ("paper_candidate", "paper_active")
    assert _card(s, "ETHUSD").verdict == "paper_candidate", _card(s, "ETHUSD").verdict   # positive control
    assert _card(s, "AVAXUSD").verdict == "rejected", _card(s, "AVAXUSD").verdict
    assert _card(s, "DOGEUSD").verdict not in paper_allowed, _card(s, "DOGEUSD").verdict  # zero sample
    # insufficient sample but positive core -> 'promising' (NOT a paper candidate)
    assert _card(s, "LINKUSD").verdict not in paper_allowed, _card(s, "LINKUSD").verdict
    assert _card(s, "LINKUSD").verdict in ("unproven", "watch", "promising"), _card(s, "LINKUSD").verdict
    s.close()
    print("strict-promotion: full evidence -> paper_candidate; negative->rejected; zero/thin -> not promoted — PASS")


def test_no_candidate_count_from_weak_only() -> None:
    s = _mem()
    _run(s, "neg2", "crypto_push_pull_momentum", "UNI/USD", sample=26, exp=-0.019, pf=0.0, dd=39.0)
    s.commit()
    out = AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    assert out["paper_candidates"] == 0, out
    s.close()
    print("strict-promotion: weak-only evidence -> 0 paper candidates — PASS")


if __name__ == "__main__":
    test_full_evidence_promotes_others_do_not()
    test_no_candidate_count_from_weak_only()
    print("ALL PASS: verify_no_paper_candidate_without_full_evidence")
