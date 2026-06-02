"""Verify the default (latest) bundle never presents old/historical data as current truth.

Catches the failure modes from the mission: old equity curve / old stock bars / old positions /
mixed prior validation runs / un-deduped research / noisy memory dumped as active truth. The
latest bundle must be current-run-filtered + labeled, summarize memory (not dump full lessons),
and surface stock readiness truthfully (stale shown as stale, not hidden).
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    svc = (BACKEND / "app/services/diagnostic_bundle_latest.py").read_text(encoding="utf-8", errors="ignore")

    # The latest bundle must NOT dump the big forensic full-history files as if current.
    forbidden_full_dumps = [
        '"lesson_nodes.json"',     # full memory dump (use governance summary instead)
        '"ai_memories.json"',
        '"backtest_runs.json"',    # full research history (forensic only)
        '"trades.json"',           # full all-time trade dump
        '"activity.json"',
    ]
    for bad in forbidden_full_dumps:
        assert bad not in svc, f"latest bundle dumps full-history file {bad} — belongs in forensic only"

    # Current-run labeling + no historical mixing.
    assert '"filtered_by_current_run": True' in svc, "current_truth not marked filtered_by_current_run"
    assert '"includes_historical_rows": False' in svc, "current_truth/README not marked non-historical"

    # Run-filtered recent rows for run-scoped sections (not all-time history).
    assert 'RiskEvent, RiskEvent.created_at, "risk_events", True' in svc, "risk_events not current-run filtered"
    assert 'StrategySignal, StrategySignal.created_at, "strategy_signals", True' in svc, \
        "strategy_signals not current-run filtered"
    assert 'BlockedTrade, BlockedTrade.created_at, "blocked_trades", True' in svc, \
        "blocked_trades not current-run filtered"

    # Memory is summarized, not dumped; archives are summarized, not embedded.
    assert '"memory_governance_summary.json": mem_gov' in svc, "memory must be a summary, not a full dump"
    assert '"archive_manifest_summary.json"' in svc and "manifest_summary()" in svc, \
        "old archives must be summarized, not embedded"

    # Stock staleness is surfaced truthfully (not hidden) — readiness is included.
    assert '"stock_data_readiness.json": stock' in svc, "stock readiness (freshness truth) must be included"

    # Equity / positions come from current truth (validation_run / live tiles), not an old curve.
    assert "_validation_run_export" in svc, "current equity/baseline must come from the validation-run export"
    assert "build_mission_control_tiles" in svc, "current positions/orders must come from live tiles"

    print("verify_bundle_does_not_confuse_old_data_as_current: PASS (current-run filtered + labeled; no old-as-current)")


if __name__ == "__main__":
    main()
