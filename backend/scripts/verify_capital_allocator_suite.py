#!/usr/bin/env python3
"""Verify capital allocator + autonomous paper learning (no arbitrary caps)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.capital_allocator import CapitalAllocatorService, _unlimited
from app.services.config_manager import ConfigManager
from app.services.default_config import DEFAULT_CONFIG
from app.services.live_lock_tripwire import live_lock_tripwire_status


def ok(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def main() -> int:
    init_db()
    errors = 0
    with Session(engine) as session:
        cfg_mgr = ConfigManager(session)
        cfg = cfg_mgr.get_current()

        apl = dict(cfg.get("autonomous_paper_learning") or {})
        ok(_unlimited(apl.get("max_paper_trades_per_day", 5)), "no fixed daily paper trade cap in config")
        ok(_unlimited(apl.get("max_open_paper_positions", 1)), "no max_open_paper_positions=1 cap")

        alloc_cfg = dict(cfg.get("capital_allocator") or DEFAULT_CONFIG.get("capital_allocator") or {})
        ok(float(alloc_cfg.get("max_single_stock_exposure_weight", 0)) < 1, "single stock weight below 100%")
        ok(float(alloc_cfg.get("max_single_crypto_exposure_weight", 0)) < 1, "single crypto weight below 100%")
        ok(int(alloc_cfg.get("operator_emergency_max_open_positions", 0)) <= 0, "emergency position guard off by default")

        svc = CapitalAllocatorService(session, cfg)
        plan = svc.build_plan()
        ok(plan.get("paper_only") is True, "allocator is paper only")
        ok(plan.get("live_trading_locked") is True, "allocator does not unlock live")

        deploy = float(plan.get("deployable_capital") or 0)
        stock_b = float(plan.get("stock_hold_budget") or 0)
        crypto_b = float(plan.get("crypto_push_pull_budget") or 0)
        if deploy > 0:
            ok(stock_b < deploy, "no single stock class gets 100% deployable")
            ok(crypto_b < deploy or plan.get("current_market_mode") == "DEGRADED_BROKER_DATA", "crypto budget bounded")

        max_single_stock = deploy * float(alloc_cfg.get("max_single_stock_exposure_weight", 0.25))
        for row in plan.get("per_symbol_budget") or []:
            if row.get("asset_class") == "stock" and stock_b > 0:
                ok(float(row.get("approved_notional") or 0) <= max_single_stock + 0.01, "no stock gets 100% budget")

        trip = live_lock_tripwire_status(cfg)
        ok(trip.get("live_lock_status") == "locked" or trip.get("live_orders_enabled") is False, "live lock remains")

        approval = svc.approve_trade("BAT/USDC", "buy", "crypto_push_pull", 50.0)
        if approval.get("reason_code") in ("quote_currency", "unsupported_quote", "allocator_degraded"):
            ok(True, "USDC unfunded or degraded blocks before broker")
        else:
            ok(approval.get("approved") in (True, False), "approve_trade returns decision")

        from app.services.aggressive_paper_learning_service import AggressivePaperLearningService

        pl = AggressivePaperLearningService(session)
        ok(pl._allocator_active(), "aggressive paper uses capital allocator")
        ok(pl._unlimited_cap("max_experiment_trades_per_day"), "no daily experiment trade cap when unlimited")

        from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService

        apl_svc = AutonomousPaperLearningService(session, cfg)
        cap = apl_svc._learning_capacity()
        ok(cap.get("daily_paper_trade_cap") is None, "learning capacity shows no fixed daily cap")

        from app.services.export_safe import safe_export_section

        export_errors: list = []
        safe_export_section("capital_allocator_plan.json", lambda: plan, export_errors)
        ok(len(export_errors) == 0, "diagnostic section export for allocator plan")

    print("\nAll capital allocator checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
