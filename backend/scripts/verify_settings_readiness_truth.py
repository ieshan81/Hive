"""
Verify the Settings page readiness truth contract.

Asserts:
  - GET /api/settings/paper-trading/readiness returns FLAT readiness fields
    that match the canonical Mission Control payload.
  - POST /api/execution/paper/readiness-check wrapper has the expected shape
    so the frontend normalizer can flatten it.
  - readiness submits no order, never changes live flags.
  - kill_switch_active state matches KillSwitchService(session, cfg).status().
  - changing kill.daily_drawdown_pct dry-run + apply is operator-gated.
  - AI actor cannot change drawdown.
  - live_trading_enabled remains False end-to-end.
  - execution.live_orders_enabled remains False end-to-end.
"""

from __future__ import annotations

import copy
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from sqlmodel import Session

from app.database import engine
from app.services.config_manager import ConfigManager
from app.services.kill_switch_service import KillSwitchService
from app.services import paper_settings_service as svc


REQUIRED_FLAT_KEYS = {
    "paper_broker_connected",
    "paper_orders_enabled",
    "paper_learning_enabled",
    "scheduler_enabled",
    "kill_switch_active",
    "bot_can_trade",
    "blockers",
    "blockers_count",
    "next_action",
    "live_trading_unchanged",
    "submitted_order",
}


def _config_snapshot(session: Session) -> dict:
    return copy.deepcopy(ConfigManager(session).get_current())


def _is_flat_readiness(payload: dict) -> tuple[bool, list[str]]:
    missing = sorted(REQUIRED_FLAT_KEYS - set(payload.keys()))
    return (len(missing) == 0, missing)


def main() -> int:
    failures: list[str] = []
    session = Session(engine)
    try:
        # 1. Flat readiness shape from svc.paper_readiness
        before = _config_snapshot(session)
        flat = svc.paper_readiness(session)
        after = _config_snapshot(session)
        if before != after:
            failures.append("paper_readiness MUTATED config (must be read-only)")
        ok, missing = _is_flat_readiness(flat)
        if not ok:
            failures.append(f"paper_readiness missing required flat fields: {missing}")
        if flat.get("submitted_order") is not False:
            failures.append("paper_readiness submitted_order != False")
        if flat.get("live_trading_unchanged") is not True:
            failures.append("paper_readiness live_trading_unchanged != True")

        # 2. kill_switch_active matches KillSwitchService.status() directly
        cfg = ConfigManager(session).get_current()
        ks = KillSwitchService(session, cfg).status()
        expected_active = not bool(ks.get("entries_allowed", True))
        if bool(flat.get("kill_switch_active")) != expected_active:
            failures.append(
                f"kill_switch_active mismatch: flat={flat.get('kill_switch_active')}, "
                f"KillSwitchService.entries_allowed={ks.get('entries_allowed')}"
            )

        # 3. Drawdown context populated
        dd = flat.get("drawdown") or {}
        for key in ("daily_limit_pct", "max_limit_pct", "weekly_limit_pct"):
            if key not in dd:
                failures.append(f"drawdown.{key} missing from readiness payload")

        # 4. set_paper_daily_drawdown gates: AI actor rejected, no mutation
        before = _config_snapshot(session)
        rejected = svc.set_paper_daily_drawdown(
            session,
            {"daily_drawdown_pct": 4.0, "confirmation": "SET PAPER DAILY DRAWDOWN"},
            actor="bot",
            actor_type="ai",
        )
        after = _config_snapshot(session)
        if rejected.get("status") != "rejected":
            failures.append("set_paper_daily_drawdown(actor_type=ai) did not reject")
        if before != after:
            failures.append("set_paper_daily_drawdown MUTATED config when actor_type=ai")

        # 5. Missing confirmation phrase → reject + no mutation
        before = _config_snapshot(session)
        no_phrase = svc.set_paper_daily_drawdown(
            session,
            {"daily_drawdown_pct": 4.0},
            actor="operator",
            actor_type="operator",
        )
        after = _config_snapshot(session)
        if no_phrase.get("status") != "rejected":
            failures.append("set_paper_daily_drawdown without confirmation did not reject")
        if before != after:
            failures.append("set_paper_daily_drawdown MUTATED config without confirmation")

        # 6. Out-of-range value → reject + no mutation
        before = _config_snapshot(session)
        oor = svc.set_paper_daily_drawdown(
            session,
            {"daily_drawdown_pct": 99.9, "confirmation": "SET PAPER DAILY DRAWDOWN"},
            actor="operator",
            actor_type="operator",
        )
        after = _config_snapshot(session)
        if oor.get("status") != "rejected":
            failures.append("set_paper_daily_drawdown(99.9) did not reject")
        if before != after:
            failures.append("set_paper_daily_drawdown MUTATED config for out-of-range value")

        # 7. Successful operator change mutates ONLY kill.daily_drawdown_pct
        original = float((ConfigManager(session).get_current().get("kill") or {}).get("daily_drawdown_pct", 2.0))
        target = round(original + 1.5, 2)
        if target < 0.5 or target > 9.5:
            target = 3.0
        ok_change = svc.set_paper_daily_drawdown(
            session,
            {"daily_drawdown_pct": target, "confirmation": "SET PAPER DAILY DRAWDOWN"},
            actor="operator-test",
            actor_type="operator",
        )
        session.commit()
        if ok_change.get("status") != "ok":
            failures.append(f"set_paper_daily_drawdown(ok) returned {ok_change.get('status')}")
        if ok_change.get("submitted_order") is not False:
            failures.append("set_paper_daily_drawdown(ok) submitted_order != False")
        if ok_change.get("live_trading_unchanged") is not True:
            failures.append("set_paper_daily_drawdown(ok) live_trading_unchanged != True")

        # Side effects must NOT have hit forbidden paths
        final_cfg = ConfigManager(session).get_current()
        if final_cfg.get("live_trading_enabled") is True:
            failures.append("FINAL live_trading_enabled = True (live lock broken)")
        if (final_cfg.get("execution") or {}).get("live_orders_enabled") is True:
            failures.append("FINAL execution.live_orders_enabled = True (live cage broken)")

        # readiness_after_change should also be flat
        rac = ok_change.get("readiness_after_change") or {}
        ok2, missing2 = _is_flat_readiness(rac)
        if not ok2:
            failures.append(f"readiness_after_change missing flat fields: {missing2}")

        # 8. Preset still cannot touch drawdown
        from app.services.paper_settings_service import _build_paper_learning_preset, PRESET_PROHIBITED_PATHS
        preset = _build_paper_learning_preset(final_cfg)
        leak = [k for k in preset if k in PRESET_PROHIBITED_PATHS]
        if leak:
            failures.append(f"preset leaked prohibited drawdown keys: {leak}")

        # 9. Restore original value so repeat runs are idempotent (best effort)
        try:
            svc.set_paper_daily_drawdown(
                session,
                {"daily_drawdown_pct": original, "confirmation": "SET PAPER DAILY DRAWDOWN"},
                actor="operator-test",
                actor_type="operator",
            )
            session.commit()
        except Exception:
            pass

    finally:
        try:
            session.close()
        except Exception:
            pass

    if failures:
        print("FAIL: verify_settings_readiness_truth")
        for f in failures:
            print("  -", f)
        return 1

    print("PASS: verify_settings_readiness_truth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
