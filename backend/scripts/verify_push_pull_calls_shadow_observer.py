"""Push-pull tick must run shadow observer on all ranked scores, not only entry_allowed rows."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.services.push_pull_scan_service import PushPullScanService  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    alpha_blocked = {
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "trade_quality_score": 42.0,
        "push_score": 12.0,
        "entry_allowed": False,
        "no_trade_reason": "ALPHA_NOT_READY:no_alpha_scorecard",
        "bar_freshness": "fresh",
        "quote_freshness": "fresh",
    }
    scoring = {
        "scores": [alpha_blocked],
        "selected_candidate": None,
        "no_trade_reason_breakdown": {},
        "scoring_model": "test",
        "strategy_version": "test",
    }
    scan = {
        "eligible": [{"strategy_id": "crypto_push_pull_baseline", "asset_class": "crypto"}],
        "blocked": [],
    }
    svc = PushPullScanService(session, cfg)
    calls: list[dict] = []

    def _capture(row, **kwargs):
        calls.append({"symbol": row.get("symbol"), "entry_allowed": row.get("entry_allowed"), **kwargs})
        return {"observation": {"shadow_trade_id": "obs-test"}, "shadow_skip_reason": "observation_created"}

    with patch("app.services.push_pull_scan_service.build_merged_universe", return_value=[]):
        with patch("app.services.push_pull_scan_service.score_active_universe", return_value=scoring):
            with patch.object(svc.pl, "scan_experiment_eligibility", return_value=scan):
                with patch.object(svc.training, "monitor_exits"):
                    with patch(
                        "app.services.shadow_trade_service.ShadowTradeService.consider_setup",
                        side_effect=_capture,
                    ):
                        with patch(
                            "app.services.shadow_outcome_service.ShadowOutcomeService.update_open_trades",
                            return_value=None,
                        ):
                            out = svc.run_tick_scan(max_evaluate=0)

    assert calls, "shadow observer was never called"
    assert any(c["symbol"] == "BTC/USD" and c["entry_allowed"] is False for c in calls), calls
    diag = out.get("shadow_diagnostics") or {}
    assert diag.get("push_pull_shadow_observer_ran") is True, diag
    assert diag.get("rows_scored_last_tick", 0) >= 1, diag
    print("verify_push_pull_calls_shadow_observer: PASS")


if __name__ == "__main__":
    main()
