from _alpha_factory_verify_common import session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    gate = AutonomousAlphaFactoryService(session, cfg).can_trade_paper("BTC/USD", strategy_id="crypto_push_pull_baseline")
    assert gate["allowed"] is False, gate
    assert gate["reason"].startswith("ALPHA_NOT_READY"), gate
    print("verify_paper_entry_requires_alpha_candidate: PASS")
    print(gate)


if __name__ == "__main__":
    main()
