"""Shadow outcomes must never count as broker or paper validation evidence."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import select

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.database import ShadowTrade  # noqa: E402
from app.services.paper_validation_analysis_service import current_run_trade_truth  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    rows = session.exec(select(ShadowTrade)).all()
    for r in rows:
        assert r.counts_as_broker_evidence is False, r.shadow_trade_id
        assert not (r.outcome_json or {}).get("counts_as_broker_evidence"), r.shadow_trade_id

    truth = current_run_trade_truth(session, cfg)
    for key in ("current_run_order_attempts", "current_run_closed_trades", "broker_fills"):
        val = truth.get(key)
        if isinstance(val, list):
            for item in val:
                assert "shadow_trade_id" not in str(item), item
    print("verify_shadow_outcomes_not_broker_evidence: PASS")


if __name__ == "__main__":
    main()
