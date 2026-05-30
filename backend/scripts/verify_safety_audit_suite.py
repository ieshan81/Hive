"""Safety audit verification suite (Phases 1–6)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

SCRIPTS = [
    "verify_broker_reconciliation_suite.py",
    "verify_flat_historical_not_ghost_candidate.py",
    "verify_paper_broker_blocks_submission.py",
    "verify_live_lock_tripwire.py",
    "verify_worker_requires_explicit_enable.py",
    "verify_strategy_import_sandbox.py",
    "verify_meme_spike_timeframes.py",
    "verify_quote_age_not_hardcoded.py",
    "verify_exit_monitor_single_call.py",
    "verify_exit_plan_self_healing.py",
    "verify_paper_exit_monitor.py",
]


def main():
    failed = []
    for name in SCRIPTS:
        path = ROOT / "scripts" / name
        if not path.exists():
            print(f"SKIP missing {name}")
            continue
        print(f"\n=== {name} ===")
        r = subprocess.run([PY, str(path)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(name)
    if failed:
        print(f"\nFAILED: {failed}")
        sys.exit(1)
    print("\nALL_SAFETY_AUDIT_CHECKS_PASSED")


if __name__ == "__main__":
    main()
