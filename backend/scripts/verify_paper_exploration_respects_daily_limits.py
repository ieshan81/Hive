"""Exploration respects the max-entries-per-day cap: once the day's probe budget is spent,
no further exploration entries are allowed (exits and real-money rules are unaffected)."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import SettingsActionAudit  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)
    cap = svc.max_entries_per_day
    assert svc.entries_today() == 0
    assert svc.permission()["paper_exploration_allowed"] is True

    # Record `cap` submitted exploration probes today (the submit path writes these audits).
    for i in range(cap):
        session.add(SettingsActionAudit(action="paper_exploration_order", details_json={"submitted": True, "i": i}))
    # A blocked (not submitted) probe must NOT count toward the cap.
    session.add(SettingsActionAudit(action="paper_exploration_order", details_json={"submitted": False}))
    session.commit()

    assert svc.entries_today() == cap, svc.entries_today()
    perm = svc.permission()
    assert perm["paper_exploration_allowed"] is False, perm
    assert "exploration_daily_entry_cap" in str(perm["paper_exploration_block_reason"]), perm
    # Exits are still allowed; real money still locked.
    assert perm["exit_management_allowed"] is True and perm["real_money_entries_allowed"] is False, perm
    print(f"verify_paper_exploration_respects_daily_limits: PASS (cap {cap}/day)")


if __name__ == "__main__":
    main()
