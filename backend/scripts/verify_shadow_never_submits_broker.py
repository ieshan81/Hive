"""Delegate to shadow broker submit guard verifier."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    for name in ("verify_shadow_trade_never_submits_broker.py", "verify_no_broker_submit_from_shadow.py"):
        r = subprocess.run([sys.executable, str(ROOT / name)], check=False)
        if r.returncode != 0:
            raise SystemExit(r.returncode)
    print("verify_shadow_never_submits_broker: PASS")


if __name__ == "__main__":
    main()
