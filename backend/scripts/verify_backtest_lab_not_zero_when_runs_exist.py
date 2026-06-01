from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.services.research_lab_service import ResearchLabService


def main() -> None:
    session, _cfg = session_with_config()
    seed_backtest(session)
    st = ResearchLabService(session).status()
    assert int(st["backtest_run_count"]) >= 1, st
    print("verify_backtest_lab_not_zero_when_runs_exist: PASS")
    print({"backtest_run_count": st["backtest_run_count"]})


if __name__ == "__main__":
    main()
