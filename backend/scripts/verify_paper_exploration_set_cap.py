"""Operator set-cap endpoint: sets the paper-exploration notional cap within (0, $25], audits the
change, submits NO order, never touches live flags, and forbids the AI actor. Above $25 is rejected.
At $12 a candidate becomes broker-valid."""

import os

os.environ["HIVE_ALLOW_UNAUTHENTICATED_DEV"] = "1"  # operator dev-bypass (no secret in test env)

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.config_manager import ConfigManager  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)
    assert svc.cap_max_usd == 25.0, svc.cap_max_usd

    # Reject out of range; cap unchanged.
    assert svc.set_exploration_cap(30, operator="op")["status"] == "rejected"
    assert svc.set_exploration_cap(0, operator="op")["status"] == "rejected"
    assert svc.set_exploration_cap(25.01, operator="op")["status"] == "rejected"

    # Valid set to $12: ok, no order, live untouched.
    out = svc.set_exploration_cap(12, operator="op")
    session.commit()
    assert out["status"] == "ok" and out["exploration_max_notional_usd"] == 12.0, out
    assert out["orders_created"] == 0, out
    assert out["live_trading_enabled"] is False and out["real_money_entries_allowed"] is False, out

    active = ConfigManager(session).get_current()
    assert (active["alpha_factory"]["paper_exploration"]["exploration_max_notional_usd"]) == 12.0, active
    assert active.get("live_trading_enabled") in (False, None), active
    assert (active.get("execution") or {}).get("live_orders_enabled") in (False, None), active

    # At $12 a candidate is broker-valid (>= ~$10.2 min with buffer).
    svc12 = PaperExplorationService(session)
    bv = svc12.broker_validity(nm())
    assert bv["broker_valid"] is True, bv
    assert svc12.max_notional_usd == 12.0, svc12.max_notional_usd

    # $25 is the boundary and is accepted; $25.01 already rejected above.
    assert svc12.set_exploration_cap(25, operator="op")["status"] == "ok"
    session.commit()

    # --- endpoint: AI actor forbidden ---
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app

    client = TestClient(app)
    H = {"X-Operator-Token": settings.operator_secret or ""}  # in-process; never printed
    # AI actor forbidden even with a valid operator token.
    r_ai = client.post("/api/alpha-factory/paper-exploration/set-cap", json={"cap_usd": 12, "actor": "ai"}, headers=H)
    assert r_ai.status_code == 403, ("AI actor must be forbidden", r_ai.status_code)
    r_over = client.post("/api/alpha-factory/paper-exploration/set-cap", json={"cap_usd": 50, "operator": "op"}, headers=H)
    assert r_over.status_code == 200 and r_over.json()["status"] == "rejected", r_over.text[:200]
    r_ok = client.post("/api/alpha-factory/paper-exploration/set-cap", json={"cap_usd": 12, "operator": "op"}, headers=H)
    assert r_ok.status_code == 200 and r_ok.json()["status"] == "ok", r_ok.text[:200]
    assert r_ok.json()["exploration_max_notional_usd"] == 12.0, r_ok.json()
    assert r_ok.json()["orders_created"] == 0, r_ok.json()
    print("verify_paper_exploration_set_cap: PASS (cap=$12; >$25 rejected; AI forbidden; no order; live untouched)")


if __name__ == "__main__":
    main()
