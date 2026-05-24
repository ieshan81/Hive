"""Kill switch blocks entries."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.kill_switch_service import KillSwitchService


class FakeSession:
    def get(self, *a, **k):
        return None

    def exec(self, *a, **k):
        class R:
            def all(self):
                return []

        return R()

    def add(self, _):
        pass


def test_manual_kill():
    config = dict(DEFAULT_CONFIG)
    config["kill"]["manual_master_active"] = True
    ok, switches = KillSwitchService(FakeSession(), config).evaluate(equity=200, daily_pl_pct=0, drawdown_pct=0)
    assert not ok
    assert any(s["switch_name"] == "manual_master" for s in switches)
    print("verify_kill_switches: PASS")


if __name__ == "__main__":
    test_manual_kill()
