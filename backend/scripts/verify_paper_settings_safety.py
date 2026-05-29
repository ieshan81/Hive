"""
Verify the Paper Settings service safety contract.

Asserts:
  - GET settings does not mutate config
  - dry-run does not mutate config
  - apply rejects AI actor
  - apply cannot change live_trading_enabled
  - apply cannot change execution.live_orders_enabled
  - apply cannot change Alpaca live URL
  - apply writes audit/config change
  - readiness check submits no order
  - live remains locked
"""

from __future__ import annotations

import copy
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import logging

logging.disable(logging.CRITICAL)

from sqlmodel import Session, select

from app.database import engine, ConfigCurrent, ConfigHistory
from app.services.config_manager import ConfigManager
from app.services import paper_settings_service as svc


def _config_snapshot(session: Session) -> dict:
    return copy.deepcopy(ConfigManager(session).get_current())


def main() -> int:
    failures: list[str] = []

    with Session(engine) as session:
        # 1. settings_status is non-mutating
        before = _config_snapshot(session)
        st = svc.settings_status(session)
        if not isinstance(st, dict) or st.get("status") != "ok":
            failures.append("settings_status did not return ok")
        after = _config_snapshot(session)
        if before != after:
            failures.append("settings_status MUTATED config (must be read-only)")

        # 2. paper_settings is non-mutating
        before = _config_snapshot(session)
        ps = svc.paper_settings(session)
        after = _config_snapshot(session)
        if before != after:
            failures.append("paper_settings MUTATED config (must be read-only)")
        if "allowed_paths" not in ps or "forbidden_paths" not in ps:
            failures.append("paper_settings missing allowed/forbidden paths")

        # 3. paper_readiness is non-mutating and submits no order
        before = _config_snapshot(session)
        rd = svc.paper_readiness(session)
        after = _config_snapshot(session)
        if before != after:
            failures.append("paper_readiness MUTATED config (must be read-only)")
        if rd.get("submitted_order") is not False:
            failures.append("paper_readiness submitted_order != False")
        if rd.get("live_trading_unchanged") is not True:
            failures.append("paper_readiness live_trading_unchanged != True")

        # 4. dry_run never mutates config
        before = _config_snapshot(session)
        dr = svc.dry_run(session, {"preset": "paper_learning_v1"})
        after = _config_snapshot(session)
        if before != after:
            failures.append("dry_run MUTATED config")
        if dr.get("submitted_order") is not False or dr.get("live_trading_unchanged") is not True:
            failures.append("dry_run did not assert no-submit / live-unchanged")
        if not dr.get("changed_keys"):
            failures.append("dry_run produced no changed_keys for preset")

        # 5. apply rejects AI actor without mutating config
        before = _config_snapshot(session)
        out = svc.apply(
            session,
            {"preset": "paper_learning_v1", "confirmation": "APPLY PAPER LEARNING PRESET"},
            actor="bot",
            actor_type="ai",
        )
        after = _config_snapshot(session)
        if before != after:
            failures.append("apply MUTATED config when actor_type=ai")
        if out.get("status") != "rejected":
            failures.append("apply did not reject ai actor")

        # 6. apply silently refuses forbidden-path changes (no mutation)
        before = _config_snapshot(session)
        out = svc.apply(
            session,
            {
                "changes": {
                    "live_trading_enabled": True,
                    "execution.live_orders_enabled": True,
                    "alpaca_base_url": "https://api.alpaca.markets",
                },
                "reason": "attempted forbidden writes",
            },
            actor="test",
            actor_type="operator",
        )
        after = _config_snapshot(session)
        if before != after:
            failures.append("apply MUTATED config on forbidden paths")
        if after.get("live_trading_enabled") is True:
            failures.append("live_trading_enabled became True after attempted change")
        if (after.get("execution") or {}).get("live_orders_enabled") is True:
            failures.append("execution.live_orders_enabled became True after attempted change")
        if out.get("status") not in ("noop", "ok"):
            failures.append(f"apply on forbidden paths unexpected status={out.get('status')}")

        # 7. apply with allowed paper-only change writes ConfigHistory
        history_before = len(list(session.exec(select(ConfigHistory)).all()))
        out = svc.apply(
            session,
            {
                "changes": {"execution.max_paper_notional_per_trade_usd": 7},
                "reason": "test bump",
            },
            actor="operator-test",
            actor_type="operator",
        )
        session.commit()
        history_after = len(list(session.exec(select(ConfigHistory)).all()))
        if out.get("submitted_order") is not False:
            failures.append("allowed-change apply submitted_order != False")
        if out.get("live_trading_unchanged") is not True:
            failures.append("allowed-change apply live_trading_unchanged != True")
        if history_after <= history_before:
            failures.append("ConfigHistory not appended after allowed change (audit log missing)")

        # 8. After all of this, live flags must remain False
        final = ConfigManager(session).get_current()
        if final.get("live_trading_enabled") is True:
            failures.append("FINAL live_trading_enabled = True (live lock broken)")
        if (final.get("execution") or {}).get("live_orders_enabled") is True:
            failures.append("FINAL execution.live_orders_enabled = True (live cage broken)")

    if failures:
        print("FAIL: verify_paper_settings_safety")
        for f in failures:
            print("  -", f)
        return 1

    print("PASS: verify_paper_settings_safety")
    return 0


if __name__ == "__main__":
    sys.exit(main())
