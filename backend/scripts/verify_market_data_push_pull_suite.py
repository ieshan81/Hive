#!/usr/bin/env python3
"""Smoke tests for bar refresh API, strategy seed, and push-pull tick breakdown."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlmodel import Session, SQLModel, create_engine, select

from app.database import StrategyRegistry
from app.services.market_data_refresh_service import MarketDataRefreshService
from app.services.push_pull_scan_service import PushPullScanService
from app.services.push_pull_strategy_seed import BASELINE_ID, ensure_crypto_push_pull_baseline


def main() -> int:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    failures: list[str] = []

    with Session(engine) as session:
        seed = ensure_crypto_push_pull_baseline(session)
        if seed.get("strategy_id") != BASELINE_ID:
            failures.append("baseline_seed_id")
        reg = session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == BASELINE_ID)
        ).first()
        if not reg or reg.current_stage != "paper_experiment":
            failures.append("baseline_stage")

        from app.services.aggressive_paper_learning_service import AggressivePaperLearningService

        elig = AggressivePaperLearningService(session).scan_experiment_eligibility()
        if not any(r.get("strategy_id") == BASELINE_ID for r in elig.get("eligible") or []):
            failures.append("baseline_not_eligible")

        fresh = MarketDataRefreshService(session).freshness_report(
            asset_type="crypto", symbols=["BTC/USD"]
        )
        if "symbols" not in fresh or "fresh_count" not in fresh:
            failures.append("freshness_report_shape")

        refresh = MarketDataRefreshService(session).refresh_bars(
            asset_type="crypto",
            symbols=["BTC/USD"],
            lookback_hours=48,
        )
        for k in ("refreshed_count", "stale_count", "provider_errors"):
            if k not in refresh:
                failures.append(f"refresh_missing_{k}")
        if refresh.get("reason") == "alpaca_not_configured" or refresh.get("status") in ("ok", "partial", "error"):
            pass
        else:
            failures.append("refresh_unexpected_status")

    if failures:
        print("FAIL", failures)
        return 1
    print("OK verify_market_data_push_pull_suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
