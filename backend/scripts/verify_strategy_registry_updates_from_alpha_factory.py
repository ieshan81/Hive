from _alpha_factory_verify_common import seed_backtest, session_with_config

from sqlmodel import select

from app.database import StrategyRegistry
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    seed_backtest(session)
    AutonomousAlphaFactoryService(session, cfg).run_candidate_promotion_cycle(operator="verify")
    reg = session.exec(select(StrategyRegistry).where(StrategyRegistry.strategy_id == "crypto_push_pull_baseline")).first()
    assert reg is not None, "strategy registry row missing"
    assert reg.can_trade_live is False and reg.live_locked is True, reg
    assert reg.current_stage in ("paper_candidate", "promising", "unproven", "rejected", "paper_quarantined"), reg.current_stage
    print("verify_strategy_registry_updates_from_alpha_factory: PASS")
    print({"stage": reg.current_stage, "can_trade_paper": reg.can_trade_paper, "live_locked": reg.live_locked})


if __name__ == "__main__":
    main()
