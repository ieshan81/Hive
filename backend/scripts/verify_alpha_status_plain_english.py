from _alpha_factory_verify_common import session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService


def main() -> None:
    session, cfg = session_with_config()
    st = AutonomousAlphaFactoryService(session, cfg).get_status()
    assert st["plain_english"], st
    assert "No paper trade" in st["plain_english"] or "paper candidate" in st["plain_english"], st
    print("verify_alpha_status_plain_english: PASS")
    print({"plain_english": st["plain_english"]})


if __name__ == "__main__":
    main()
