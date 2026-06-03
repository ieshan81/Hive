"""Wrapper — shadow trades never submit broker orders."""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "verify_shadow_trade_never_submits_broker.py")],
        cwd=str(BACKEND),
    )
    if r.returncode != 0:
        sys.exit(r.returncode)
    print("verify_no_broker_submit_from_shadow: PASS (delegated)")


if __name__ == "__main__":
    main()
