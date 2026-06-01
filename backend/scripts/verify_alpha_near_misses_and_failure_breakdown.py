"""Near-misses rank closest-to-qualifying with the single missing requirement; status
surfaces a failure breakdown + top cost blockers. All read-only, never promotes/trades."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import ResearchBacktestRun
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

CFG = {"alpha_factory": {"min_sample_size": 5, "min_profit_factor": 1.05}}
PAPER_ALLOWED = ("paper_candidate", "paper_active")


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _run(s, rid, strat, sym, *, sample, exp, pf, dd, metrics_extra=None):
    m = {"win_rate": 0.5, "expectancy": exp, "profit_factor": pf, "max_drawdown_pct": dd}
    m.update(metrics_extra or {})
    s.add(ResearchBacktestRun(run_id=rid, strategy_id=strat, symbols=[sym], status="completed",
                              num_trades=sample, sample_size=sample, source="autonomous_research_worker",
                              metrics_json=m))


def _pick(rows, norm):
    return next((r for r in rows if str(r["symbol"]).upper().replace("/", "") == norm), None)


def test_near_misses_and_breakdown() -> None:
    s = _mem()
    _run(s, "eth", "crypto_push_pull_baseline", "ETH/USD", sample=30, exp=0.012, pf=1.8, dd=4.0)   # paper_candidate
    _run(s, "link", "crypto_push_pull_baseline", "LINK/USD", sample=2, exp=0.01, pf=1.5, dd=3.0)    # near_miss (sample)
    _run(s, "uni", "crypto_push_pull_momentum", "UNI/USD", sample=30, exp=0.005, pf=1.3, dd=6.0,
         metrics_extra={"cost_model": {"round_trip_cost_pct": 0.008}})                              # costs_too_high
    _run(s, "avax", "crypto_push_pull_momentum", "AVAX/USD", sample=30, exp=-0.02, pf=0.5, dd=9.0)  # negative_expectancy
    s.commit()
    fac = AutonomousAlphaFactoryService(s, CFG)
    fac.bootstrap_scorecards_from_existing_evidence()
    s.commit()

    # --- PHASE 6: status failure breakdown + cost blockers + version ---
    st = fac.get_status()
    fb = st["alpha_failure_breakdown"]
    assert st["cost_model_version"] == "v2_components_no_double_count", st["cost_model_version"]
    assert fb.get("near_miss", 0) >= 1, fb
    assert fb.get("costs_too_high", 0) >= 1, fb
    assert fb.get("negative_expectancy", 0) >= 1, fb
    assert st["near_miss_count"] >= 1, st["near_miss_count"]
    blockers = {b["symbol"].upper().replace("/", "") for b in st["top_cost_blockers"]}
    assert "UNIUSD" in blockers, st["top_cost_blockers"]

    # --- PHASE 4: near-misses ranked, single missing requirement, none promoted ---
    nm = fac.get_near_misses(limit=10)
    rows = nm["near_misses"]
    assert nm["count"] >= 3, nm
    assert _pick(rows, "ETHUSD") is None, "qualified candidate must not appear in near-misses"
    # closest = LINK (positive core, only sample short)
    assert rows[0]["symbol"].upper().replace("/", "") == "LINKUSD", rows[0]["symbol"]
    assert rows[0]["missing_requirement"] == "min_sample_size", rows[0]
    uni = _pick(rows, "UNIUSD")
    assert uni and uni["missing_requirement"] == "positive_edge_after_cost", uni
    assert uni["failure_category"] == "costs_too_high", uni
    avax = _pick(rows, "AVAXUSD")
    assert avax and avax["missing_requirement"] == "positive_expectancy", avax
    for r in rows:
        assert r["verdict"] not in PAPER_ALLOWED, r          # never a tradeable candidate
        for k in ("required_metric", "current_metric", "next_research_action", "distance_to_qualify"):
            assert k in r, (k, r)
    # distances strictly non-decreasing (closest first)
    dists = [r["distance_to_qualify"] for r in rows]
    assert dists == sorted(dists), dists
    assert nm["orders_authority"] == "none"
    s.close()
    print(f"near-misses: closest={rows[0]['symbol']} needs {rows[0]['missing_requirement']}; "
          f"breakdown={fb}; cost blockers={sorted(blockers)} — PASS")


def test_old_rows_without_round_trip_not_mislabeled_missing_cost_model() -> None:
    """A pre-existing scorecard with a null round-trip cost_bps but populated spread/fee and a
    real negative after-cost edge must NOT be reported as 'missing_cost_model'."""
    from app.database import AlphaScorecard
    from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService

    s = _mem()
    # Mirrors live prod rows created before the cost_bps column was populated.
    s.add(AlphaScorecard(symbol="AVAX/USD", normalized_symbol="AVAXUSD", asset_class="crypto",
                         strategy_family="momentum_continuation", strategy_id="crypto_push_pull_momentum",
                         sample_size=26, expectancy=-0.02, profit_factor=0.5, max_drawdown_pct=9.0,
                         cost_bps=None, spread_bps=20.0, slippage_bps=20.0, fee_bps=25.0,
                         edge_after_cost_bps=-136.0, verdict="rejected"))
    s.add(AlphaScorecard(symbol="LINK/USD", normalized_symbol="LINKUSD", asset_class="crypto",
                         strategy_family="momentum_continuation", strategy_id="crypto_push_pull_baseline",
                         sample_size=0, expectancy=None, profit_factor=None, max_drawdown_pct=None,
                         cost_bps=None, spread_bps=20.0, slippage_bps=20.0, fee_bps=25.0,
                         edge_after_cost_bps=None, verdict="unproven"))
    s.commit()
    fac = AutonomousAlphaFactoryService(s, CFG)
    fb = fac.get_status()["alpha_failure_breakdown"]
    assert fb.get("missing_cost_model", 0) == 0, f"old rows mislabeled missing_cost_model: {fb}"
    assert fb.get("negative_expectancy", 0) >= 1, fb     # AVAX: real reason surfaced
    assert fb.get("data_insufficient", 0) >= 1, fb        # LINK: zero sample
    s.close()
    print(f"failure-breakdown: null round-trip not mislabeled; honest categories={fb} — PASS")


if __name__ == "__main__":
    test_near_misses_and_breakdown()
    test_old_rows_without_round_trip_not_mislabeled_missing_cost_model()
    print("ALL PASS: verify_alpha_near_misses_and_failure_breakdown")
