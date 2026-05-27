#!/usr/bin/env python3
"""Verify hybrid radar, tiers, reddit read-only, targeted experiment imports."""

from __future__ import annotations

import sys


def main() -> None:
    from app.services.universe_mode_service import get_universe_mode
    from app.services.default_config import DEFAULT_CONFIG
    from app.services.reddit_scanner_service import reddit_status
    from app.services.finbert_client import finbert_health
    from app.services.targeted_experiment_service import experiment_status
    from app.database import engine, init_db
    from sqlmodel import Session

    mode = get_universe_mode(DEFAULT_CONFIG)
    assert mode == "hybrid_radar", f"expected hybrid_radar default, got {mode}"

    rs = reddit_status()
    assert rs.get("read_only") is True
    assert rs.get("no_posting") is True

    init_db()
    with Session(engine) as s:
        exp = experiment_status(s)
        assert exp.get("paper_only") is True
        assert exp.get("live_trading") is False

    fh = finbert_health()
    assert "configured" in fh

    print("verify_hybrid_radar_suite: OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("verify_hybrid_radar_suite: FAIL", exc)
        sys.exit(1)
