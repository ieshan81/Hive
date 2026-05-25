"""Broker reconciliation verification suite."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SCRIPTS = [
    "verify_broker_flat_historical_buy_not_active_position.py",
    "verify_local_ghost_position_blocks_entries.py",
    "verify_no_fake_sell_fill_on_broker_reject.py",
    "verify_broker_reject_memory_created.py",
    "verify_doge_drawer_reconciliation_state.py",
    "verify_entries_disabled_until_operator_enable.py",
    "verify_live_lock_still_locked.py",
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
    print("\nALL_BROKER_RECONCILIATION_CHECKS_PASSED")


if __name__ == "__main__":
    main()
