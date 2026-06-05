"""Diagnostic latest bundle includes paper_canary_audit.json with gate fields."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine, init_db
    from app.services.config_manager import ConfigManager
    from app.services.diagnostic_bundle_latest import build_latest_bundle
    from app.services.paper_canary_gate_service import PaperCanaryGateService

    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        PaperCanaryGateService(session, cfg).evaluate_and_promote(operator="verify_bundle")
        session.commit()
        bundle = build_latest_bundle(session, cfg)
    audit = bundle.get("paper_canary_audit.json") or {}
    for key in (
        "gate_result",
        "qualified_shadow_closes",
        "excluded_missing_price",
        "excluded_cap_release",
        "live_trading_locked",
    ):
        assert key in audit or key in (audit.get("metrics") or {}), f"missing {key} in {audit.keys()}"
    print("verify_paper_order_audit_bundle: PASS")


if __name__ == "__main__":
    main()
