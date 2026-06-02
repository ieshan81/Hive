"""PR F — Reset-readiness gate for paper_validation_run_001.

Aggregates the safety + structural invariants that must hold before a $200 paper reset. Runs the
critical verifier battery and asserts the engine is in a clean, safe, reset-ready shape. Read-only;
submits no order; never enables live.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SCRIPTS = Path(__file__).resolve().parent

# Each must be green for reset readiness.
REQUIRED = [
    # live / cage / kill-switch safety
    "verify_live_flags_locked",
    "verify_kill_switches",
    "verify_trading_cage_architecture",
    "verify_tradingview_execution_blocked",
    # paper exploration safety
    "verify_paper_exploration_never_live",
    "verify_paper_exploration_uses_official_cage",
    "verify_paper_exploration_blocks_catastrophic_switches",
    "verify_paper_exploration_preflight_allows_daily_drawdown",
    "verify_run_exploration_real_submit_no_kill_switch_mismatch",
    # outcome truth
    "verify_closed_trade_outcome_truth",
    # memory governance
    "verify_memory_cannot_directly_trade",
    "verify_memory_hypothesis_requires_backtest",
    "verify_old_memory_archived_before_reset",
    # route / engine-map hygiene
    "verify_every_ui_endpoint_has_backend_route",
    "verify_no_dead_debug_routes_exposed",
    "verify_engine_map_truth",
    # two-loop heartbeat + evidence gate
    "verify_heartbeat_does_not_force_entries",
    "verify_exit_monitor_uses_broker_truth",
    "verify_backtest_result_required_before_paper_candidate",
    # broker connectivity (paper) + secret hygiene
    "verify_alpaca_paper_env_and_connection",
    "verify_no_secret_leak_in_logs_or_git",
]


def main() -> None:
    failed = []
    for name in REQUIRED:
        p = SCRIPTS / f"{name}.py"
        if not p.exists():
            failed.append(f"{name} (missing)")
            continue
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, timeout=320)
        if r.returncode != 0:
            failed.append(name)
    assert not failed, "Reset-readiness FAILED — these gates are not green:\n  " + "\n  ".join(failed)
    print(f"verify_reset_readiness: PASS ({len(REQUIRED)} gates green — engine is safe & reset-ready for paper_validation_run_001)")
    print("  NOTE: reset readiness = SAFE to gather evidence. It does NOT mean profitable or live-ready.")


if __name__ == "__main__":
    main()
