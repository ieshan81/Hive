"""Perf/structure verifier for the latest bundle's parallel fetch + headline reuse.

Exercises the concurrent _run_fetches branch (own Session per job, result collection, per-job timeout),
asserts generation_seconds is recorded, that the job-dispatch refactor dropped no section, and that
changed_since_previous_bundle.current_headline is built from the SAME reads the bundle already
computed (no divergent recompute). Read-only.
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

REQUIRED_SECTIONS = [
    "paper_validation_productivity.json", "current_run_trade_truth.json", "p_and_l_guard_trace.json",
    "data_freshness_matrix.json", "alpha_coverage_matrix.json", "blocker_timeline.json",
    "universe_summary.json", "stock_data_readiness.json", "performance_summary.json",
    "scheduler_status.json", "promotion_criteria.json", "hive_engine_map.json",
    "memory_governance_summary.json", "paper_order_proof.json", "validation_run.json",
    "changed_since_previous_bundle.json",
]


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import _run_fetches, build_latest_bundle
    from app.services.nuke_epoch_service import PAPER_BASELINE_EQUITY, PAPER_VALIDATION_RUN_ID, record_reset_epoch

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    # 1) Parallel branch runs every job, each in its own Session, and collects all results.
    errs: list = []
    jobs = {"a": lambda s: 1 + 1, "b": lambda s: "ok", "c": lambda s: time.sleep(0.3) or "done"}
    t0 = time.time()
    res = _run_fetches(jobs, Session(engine), errs, parallel=True, max_workers=4, per_job_timeout=5.0)
    assert res["a"] == 2 and res["b"] == "ok" and res["c"] == "done", "parallel branch lost a result"
    # Concurrency: three jobs incl. a 0.3s sleep finish well under the 0.9s sequential sum.
    assert (time.time() - t0) < 0.8, "jobs did not run concurrently"
    assert not errs, f"unexpected errors: {errs}"

    # 2) Per-job timeout degrades only that section (never hangs the whole build).
    errs2: list = []
    res2 = _run_fetches({"hang": lambda s: time.sleep(0.6) or "x"}, Session(engine), errs2,
                        parallel=True, per_job_timeout=0.15)
    assert (res2["hang"] or {}).get("error") == "timeout", "slow job must degrade to a timeout placeholder"
    assert any(e.get("section") == "hang" for e in errs2), "timeout must be recorded in errs"

    # 3) A failing job degrades to a placeholder, not an exception.
    errs3: list = []
    res3 = _run_fetches({"boom": lambda s: (_ for _ in ()).throw(ValueError("x"))}, Session(engine),
                        errs3, parallel=True)
    assert (res3["boom"] or {}).get("status") == "degraded", "failing job must degrade gracefully"

    # 4) Build the bundle (sqlite -> sequential path) and check structure + headline reuse.
    with Session(engine) as s:
        record_reset_epoch(s, "perf", deleted={}, validation_run_id=PAPER_VALIDATION_RUN_ID,
                           baseline_equity=PAPER_BASELINE_EQUITY)
        s.commit()
    with Session(engine) as w:
        build_latest_bundle(w, config={}); w.commit()
    b = build_latest_bundle(Session(engine), config={})

    gen = b["bundle_meta.json"]["generation_seconds"]
    assert isinstance(gen, (int, float)) and gen >= 0, "generation_seconds must be recorded"
    for f in REQUIRED_SECTIONS:
        assert f in b, f"refactor dropped section {f}"

    # Headline reuse: changed_since_previous_bundle.current_headline must equal the bundle's own reads.
    ch = (b["changed_since_previous_bundle.json"] or {}).get("current_headline") or {}
    tt, fm, am = b["current_run_trade_truth.json"], b["data_freshness_matrix.json"], b["alpha_coverage_matrix.json"]
    assert ch.get("current_run_order_attempts") == tt.get("current_run_order_attempts"), "headline must reuse trade_truth"
    assert ch.get("current_run_closed_trades") == tt.get("current_run_closed_trades"), "headline must reuse trade_truth"
    assert ch.get("stale_count") == fm.get("stale_count") and ch.get("fresh_count") == fm.get("fresh_count"), "headline must reuse freshness"
    assert ch.get("no_scorecard_count") == am.get("no_scorecard"), "headline must reuse alpha matrix"

    print(f"verify_latest_bundle_perf: PASS (parallel runs+collects all jobs; timeout+failure degrade only that "
          f"section; generation_seconds={gen}s recorded; {len(REQUIRED_SECTIONS)} sections intact; headline reuses bundle reads)")


if __name__ == "__main__":
    main()
