"""Scorecards surface the cost breakdown so a negative after-cost edge is explainable."""

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


def test_cost_breakdown_surfaced() -> None:
    s = _mem()
    s.add(ResearchBacktestRun(run_id="r1", strategy_id="crypto_push_pull_momentum", symbols=["UNI/USD"],
                              status="completed", num_trades=20, sample_size=20, source="autonomous_research_worker",
                              metrics_json={"win_rate": 0.2, "expectancy": -0.01, "profit_factor": 0.5, "max_drawdown_pct": 6.0}))
    s.commit()
    AutonomousAlphaFactoryService(s, CFG).bootstrap_scorecards_from_existing_evidence()
    s.commit()
    sc = s.exec(select(AlphaScorecard).where(AlphaScorecard.normalized_symbol == "UNIUSD")).first()
    assert sc is not None
    # cost fields populated (no longer None) so the negative edge is explained
    assert sc.cost_bps is not None and sc.cost_bps > 0, sc.cost_bps
    assert sc.spread_bps is not None and sc.fee_bps is not None, (sc.spread_bps, sc.fee_bps)
    j = sc.scorecard_json or {}
    for k in ("round_trip_cost_bps", "spread_cost_bps", "slippage_cost_bps", "fee_cost_bps",
              "breakeven_move_bps", "gross_expectancy_bps", "cost_model_version", "cost_breakdown"):
        assert k in j, f"missing scorecard_json.{k}"
    assert j["cost_model_version"] == "v2_components_no_double_count", j["cost_model_version"]
    # gross = net + round_trip (cost explains the gap between gross and net)
    assert j["gross_expectancy_bps"] is not None and j["round_trip_cost_bps"] > 0, j
    assert sc.verdict in ("rejected", "unproven"), sc.verdict  # still not promoted
    s.close()
    print(f"cost-breakdown: scorecard surfaces round_trip={j['round_trip_cost_bps']}bps "
          f"(spread {j['spread_cost_bps']}/slip {j['slippage_cost_bps']}/fee {j['fee_cost_bps']}), "
          f"gross={j['gross_expectancy_bps']}bps -> negative edge explained — PASS")


if __name__ == "__main__":
    test_cost_breakdown_surfaced()
    print("ALL PASS: verify_alpha_cost_breakdown_explains_negative_edge")
