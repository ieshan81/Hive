"""Latest bundle generation time and section contract."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass

    with Session(engine) as session:
        t0 = time.time()
        bundle = build_latest_bundle(session)
        elapsed = time.time() - t0
        meta = bundle.get("bundle_meta.json") or {}
        gen = float(meta.get("generation_seconds") or elapsed)
        assert meta.get("bundle_mode") == "latest", meta
        assert "README_FIRST.json" in bundle
        assert "paper_validation_productivity.json" in bundle
        prod = bundle.get("paper_validation_productivity.json") or {}
        assert prod.get("status") != "degraded" or prod.get("error") != "timeout", prod
        assert prod.get("why_no_trade") or prod.get("why_no_paper_trade_plain"), prod
        errors = meta.get("section_errors") or []
        timeouts = [e for e in errors if isinstance(e, dict) and e.get("error") == "timeout"]
        assert not any(
            (e.get("section") or "") in ("productivity", "shadow_bundle") for e in timeouts
        ), f"bundle section timeout: {timeouts}"
        shadow_sum = bundle.get("shadow_trades_summary.json") or {}
        assert shadow_sum.get("status") != "degraded" or shadow_sum.get("error") != "timeout", shadow_sum
        assert gen < 35.0, f"generation_seconds too high: {gen}"
        assert meta.get("section_timings"), "bundle must include section_timings"
        if gen > 10.0:
            assert meta.get("section_timings") or meta.get("section_errors") is not None, (
                "slow bundle must report timings/errors"
            )
        print(f"verify_latest_bundle_generation_reasonable: PASS (generation_seconds={gen})")


if __name__ == "__main__":
    main()
