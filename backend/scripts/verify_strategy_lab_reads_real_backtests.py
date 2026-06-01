from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.services.alpha_research_read_model_service import AlphaResearchReadModelService


def main() -> None:
    session, cfg = session_with_config()
    seed_backtest(session)
    runs = AlphaResearchReadModelService(session, cfg).research_runs()
    # ResearchJob may be empty, but the status/read model should point to latest persisted backtest.
    st = AlphaResearchReadModelService(session, cfg).status()
    assert st["latest_backtest_at"] is not None, st
    print("verify_strategy_lab_reads_real_backtests: PASS")
    print({"latest_backtest_at": st["latest_backtest_at"], "job_count": len(runs["jobs"])})


if __name__ == "__main__":
    main()
