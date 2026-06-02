"""Phase 6 verifier: the adapter submit guard is config-aware and fails closed.

Asserts the submission guard blocks when the runtime config says live is enabled, allows a normal
paper config, and that the adapter routes every submit through the config-aware _guard_submission
that fails closed when no config/safety context is available. No broker order is submitted.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("LIVE_TRADING_ARMED", None)
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.broker_submission_guard import assert_paper_submission_allowed, guard_before_submit  # noqa: E402


def main() -> None:
    # Live flags in config -> blocked.
    ok, code = assert_paper_submission_allowed({"execution": {"live_orders_enabled": True}})
    assert not ok and code in ("live_flags_set", "LIVE_TRADING_ARMED", "env_unsafe", "broker_not_paper"), f"live config not blocked: {code}"
    assert guard_before_submit({"live_trading_enabled": True}) is not None, "live_trading config must block"

    # Normal paper config -> allowed (paper broker URL from env; no live flags; not armed).
    paper_cfg = {"execution": {"live_orders_enabled": False, "paper_orders_enabled": True}, "live_trading_enabled": False}
    assert guard_before_submit(paper_cfg) is None, "normal paper config should be allowed"

    # Adapter routes through the config-aware guard and fails closed on missing context.
    src = (BACKEND / "app/services/alpaca_adapter.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert "def _guard_submission" in src, "adapter must define config-aware _guard_submission"
    assert "blocked = self._guard_submission()" in src, "adapter submits must use _guard_submission"
    assert "blocked = guard_before_submit()" not in src, "adapter must not call the no-arg (config-blind) guard"
    assert "ConfigManager(self.session).get_current()" in src, "guard must load runtime config"
    assert ("PAPER_PROTECTION_CONTEXT_UNAVAILABLE" in src or "NO_CONFIG_CONTEXT" in src), "guard must fail closed on missing config"

    print("verify_adapter_submit_guard_config_aware: PASS (live config blocked; paper allowed; adapter config-aware + fail-closed)")


if __name__ == "__main__":
    main()
