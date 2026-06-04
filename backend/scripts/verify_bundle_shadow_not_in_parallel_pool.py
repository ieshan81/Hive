"""Shadow bundle must not run inside the 6s parallel job pool (prod timeout root cause)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "services" / "diagnostic_bundle_latest.py"


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    jobs_block = re.search(r"jobs\s*=\s*\{([^}]+)\}", text, re.DOTALL)
    assert jobs_block, "jobs dict not found"
    assert '"shadow_bundle"' not in jobs_block.group(1) and "'shadow_bundle'" not in jobs_block.group(1), (
        "shadow_bundle must not be in parallel jobs"
    )
    assert "shadow_bundle_seconds" in text, "missing shadow_bundle_seconds timing"
    assert '_safe("shadow_bundle"' in text or "_safe('shadow_bundle'" in text, "shadow_bundle must run sequentially"
    print("verify_bundle_shadow_not_in_parallel_pool: PASS")


if __name__ == "__main__":
    main()
