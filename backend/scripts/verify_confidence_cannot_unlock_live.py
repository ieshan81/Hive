"""Confidence engine must never unlock live trading."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.confidence_engine import ConfidenceEngine, can_unlock_live


def main() -> None:
    init_db()
    with Session(engine) as session:
        assert can_unlock_live() is False
        summary = ConfidenceEngine(session).summary()
        assert summary.get("can_unlock_live") is False
    print("PASS: confidence cannot unlock live")


if __name__ == "__main__":
    main()
