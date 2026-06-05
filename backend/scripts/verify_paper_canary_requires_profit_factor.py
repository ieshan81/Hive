"""Aggregate paper-canary gate fails when profit factor is below threshold."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_canary_gate_service import evaluate_aggregate_gate  # noqa: E402


def main() -> None:
    cfg = {"shadow_league": {"paper_canary": {"min_profit_factor": 1.10, "min_qualified_closes": 3}}}
    metrics = {
        "qualified_closes": 10,
        "avg_pnl_bps_after_cost": 5.0,
        "profit_factor": 1.05,
        "win_rate": 0.55,
        "zero_pnl_fraction": 0.1,
    }
    gate = evaluate_aggregate_gate(metrics, cfg)
    assert not gate["aggregate_gate_passed"]
    assert "profit_factor_below_threshold" in gate["gate_failures"]
    metrics["profit_factor"] = 1.15
    gate2 = evaluate_aggregate_gate(metrics, cfg)
    assert "profit_factor_below_threshold" not in (gate2.get("gate_failures") or [])
    print("verify_paper_canary_requires_profit_factor: PASS")


if __name__ == "__main__":
    main()
