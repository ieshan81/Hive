"""Productivity endpoint fast + complete contract (FINAL pass)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    for name in ("verify_productivity_fast.py", "verify_paper_validation_productivity_truth.py"):
        r = subprocess.run([sys.executable, str(ROOT / name)], check=False)
        if r.returncode != 0:
            raise SystemExit(r.returncode)
    print("verify_paper_validation_productivity_fast_and_complete: PASS (delegated)")


if __name__ == "__main__":
    main()
