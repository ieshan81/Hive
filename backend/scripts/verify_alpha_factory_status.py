from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_backtest(session)
    svc = AutonomousAlphaFactoryService(session, cfg)
    svc.run_candidate_promotion_cycle(operator="verify")
    st = svc.get_status()
    assert st["status"] == "ok", st
    assert "can_trade_paper_now" in st, st
    assert st["paper_candidate_count"] >= 1, st
    print("verify_alpha_factory_status: PASS")
    print({"can_trade_paper_now": st["can_trade_paper_now"], "reason": st["reason"], "best_candidate": st["best_candidate"]})


if __name__ == "__main__":
    main()
