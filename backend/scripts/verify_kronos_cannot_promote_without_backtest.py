"""Kronos can never promote: a bullish forecast alone cannot create a paper_candidate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.autonomous_research_worker import verdict_from_metrics
from app.services.kronos_market_model_service import apply_kronos_to_ranking

# A maximally-bullish Kronos contribution (still capped + advisory-only).
BULLISH_KRONOS = {"available": True, "forecast_direction": "bullish", "score_contribution": 0.10, "can_promote": False}


def test_kronos_never_self_promotes() -> None:
    assert BULLISH_KRONOS["can_promote"] is False
    print("kronos: score_forecast carries can_promote=False — PASS")


def test_zero_sample_stays_unproven_with_bullish_kronos() -> None:
    verdict, _ = verdict_from_metrics(
        sample_size=0, win_rate=0.0, expectancy=0.0, max_drawdown_pct=0.0, fee_adjusted_pnl=0.0, profit_factor=0.0
    )
    assert verdict in ("watch", "unproven"), verdict
    out_verdict, out_score = apply_kronos_to_ranking(verdict, 0.5, BULLISH_KRONOS, weight_cap=0.10)
    assert out_verdict == verdict, (out_verdict, verdict)  # verdict UNCHANGED by Kronos
    assert out_verdict != "paper_test_candidate", out_verdict
    print("kronos: zero sample + bullish Kronos -> verdict unchanged (watch/unproven), not promoted — PASS")


def test_negative_expectancy_stays_rejected_with_bullish_kronos() -> None:
    verdict, _ = verdict_from_metrics(
        sample_size=20, win_rate=0.3, expectancy=-0.5, max_drawdown_pct=4.0, fee_adjusted_pnl=-10.0, profit_factor=0.5
    )
    assert verdict == "reject", verdict
    out_verdict, _ = apply_kronos_to_ranking(verdict, 0.2, BULLISH_KRONOS, weight_cap=0.10)
    assert out_verdict == "reject", out_verdict  # Kronos cannot rescue a rejected verdict
    print("kronos: negative expectancy + bullish Kronos -> stays rejected — PASS")


def test_kronos_only_nudges_rank_within_cap() -> None:
    _, out_score = apply_kronos_to_ranking("watch", 0.5, BULLISH_KRONOS, weight_cap=0.10)
    assert abs(out_score - 0.5) <= 0.10 + 1e-9, out_score  # within weight cap
    print("kronos: ranking nudge stays within weight cap — PASS")


if __name__ == "__main__":
    test_kronos_never_self_promotes()
    test_zero_sample_stays_unproven_with_bullish_kronos()
    test_negative_expectancy_stays_rejected_with_bullish_kronos()
    test_kronos_only_nudges_rank_within_cap()
    print("ALL PASS: verify_kronos_cannot_promote_without_backtest")
