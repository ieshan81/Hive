from _alpha_factory_verify_common import session_with_config

from app.services.autonomous_alpha_scheduler import AutonomousAlphaScheduler


def main() -> None:
    session, cfg = session_with_config()
    sched = AutonomousAlphaScheduler(session, cfg)
    st = sched.status()
    assert "enabled" in st, st
    skipped = sched.pause(operator="verify")
    assert skipped["status"] == "ok" and skipped["enabled"] is False, skipped
    resumed = sched.resume(operator="verify")
    assert resumed["status"] == "ok" and resumed["enabled"] is True, resumed
    print("verify_autonomous_alpha_scheduler_status: PASS")
    print(sched.status())


if __name__ == "__main__":
    main()
