#!/usr/bin/env python3
"""Verify DB pool status helper."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.system_db_pool_service import db_pool_status


def main() -> int:
    st = db_pool_status()
    assert "status" in st
    assert "degraded" in st
    print("verify_db_pool_resilience: OK", st.get("status"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("verify_db_pool_resilience: FAIL", exc)
        sys.exit(1)
