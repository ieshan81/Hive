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
        assert gen < 30.0, f"generation_seconds too high: {gen}"
        if gen > 10.0:
            assert meta.get("section_timings") or meta.get("section_errors") is not None, (
                "slow bundle must report timings/errors"
            )
        print(f"verify_latest_bundle_generation_reasonable: PASS (generation_seconds={gen})")


if __name__ == "__main__":
    main()
