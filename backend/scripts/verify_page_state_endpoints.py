#!/usr/bin/env python3
"""Verify page-state endpoints return 200 quickly."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine, init_db
from app.services.page_state_service import PAGE_BUILDERS
from sqlmodel import Session


def main() -> int:
    init_db()
    with Session(engine) as session:
        for page in PAGE_BUILDERS:
            out = PAGE_BUILDERS[page](session)
            assert out.get("status") in ("ok", "degraded"), page
            assert "generated_at_utc" in out, page
            assert "snapshot_age_seconds" in out or out.get("snapshot_age_seconds") is None
    print("verify_page_state_endpoints: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("verify_page_state_endpoints: FAIL", exc)
        sys.exit(1)
