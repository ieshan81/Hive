"""Run all exit min-notional verification scripts."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SCRIPTS = [
    "verify_full_position_exit_not_blocked_by_entry_min_notional.py",
    "verify_partial_exit_below_min_notional_still_blocked.py",
    "verify_exit_min_notional_exemption_requires_broker_qty.py",
    "verify_exit_min_notional_exemption_requires_paper_lock.py",
    "verify_exit_min_notional_exemption_does_not_apply_to_buys.py",
    "verify_no_duplicate_exit_order.py",
    "verify_broker_rejected_min_notional_only_when_broker_rejects.py",
]


def main():
    failed = []
    for name in SCRIPTS:
        print(f"\n=== {name} ===")
        r = subprocess.run([PY, str(ROOT / "scripts" / name)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(name)
    if failed:
        print(f"\nFAILED: {failed}")
        sys.exit(1)
    print("\nALL_EXIT_MIN_NOTIONAL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
