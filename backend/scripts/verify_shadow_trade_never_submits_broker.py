"""Shadow trade creation must never call PaperExecutionService or broker submit."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.shadow_trade_service import ShadowTradeService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    row = {
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "trade_quality_score": 0.55,
        "push_score": 0.01,
        "entry_allowed": False,
        "no_trade_reason": "ALPHA_NOT_READY",
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
    }
    svc = ShadowTradeService(session, cfg)
    with patch("app.services.paper_execution_service.PaperExecutionService.submit_candidate", MagicMock()) as submit:
        with patch("app.services.paper_execution_service.PaperExecutionService.candidate_from_signal", MagicMock()):
            out = svc.consider_setup(row, strategy_id="crypto_push_pull_baseline", paper_blocked_reason="ALPHA_NOT_READY")
    submit.assert_not_called()
    assert out.get("observation") or out.get("shadow_trade"), out
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "shadow_trade_service.py"
    text = src.read_text(encoding="utf-8")
    assert "PaperExecutionService" not in text
    assert "submit_candidate" not in text
    print("verify_shadow_trade_never_submits_broker: PASS")


if __name__ == "__main__":
    main()
