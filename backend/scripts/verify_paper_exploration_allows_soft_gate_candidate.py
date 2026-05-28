"""Verify paper exploration treats weak soft gates as ranking concerns, not blockers."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.trading_cage.push_pull_engine import score_push_pull_setup


def cfg(exploration: bool) -> dict:
    out = copy.deepcopy(DEFAULT_CONFIG)
    out["promotion"] = {"current_stage": "PAPER"}
    out["exploration"] = {"enabled": exploration, "dynamic_formula_mode": True}
    out["autonomous_paper_learning"] = {
        **(out.get("autonomous_paper_learning") or {}),
        "mode_enabled": exploration,
    }
    out["push_pull"] = {
        **(out.get("push_pull") or {}),
        "enter_threshold": 0.70,
        "min_trade_quality": 0.60,
        "paper_exploration_enter_floor": 0.42,
        "paper_exploration_min_quality": 0.38,
    }
    return out


def score(config: dict):
    return score_push_pull_setup(
        config,
        symbol="BTC/USD",
        momentum_1h=0.001,
        body_pct=0.12,
        volume_spike=0.8,
        spread_pct=0.001,
        quote_age_seconds=2,
        bar_age_minutes=3,
        vwap_confirm=False,
        ema_confirm=False,
        atr_valid=True,
        overextension=0.5,
        expected_move_pct=2.0,
        tier="TIER_MAJOR",
        pattern_confidence=0.95,
        pullback_quality_score=0.9,
        reversal_risk_score=0.1,
        continuation_score=0.9,
    )


def main() -> None:
    exploratory = score(cfg(True))
    strict = score(cfg(False))

    assert exploratory.entry_allowed is True
    assert exploratory.no_trade_reason is None
    assert "candle_quality" in exploratory.evidence.get("soft_concerns", [])
    assert "volume_spike" in exploratory.evidence.get("soft_concerns", [])
    assert strict.entry_allowed is False
    assert strict.no_trade_reason in {
        "PUSH_BELOW_THRESHOLD",
        "CANDLE_QUALITY",
        "VOLUME_SPIKE",
        "VWAP_CONFIRMATION",
        "EMA_CONFIRMATION",
    }
    print("verify_paper_exploration_allows_soft_gate_candidate: PASS")


if __name__ == "__main__":
    main()
