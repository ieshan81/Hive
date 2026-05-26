"""Ensure paper-experiment push-pull strategy exists for autonomous learning."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import StrategyRegistry
from app.services.config_manager import ConfigManager


BASELINE_ID = "crypto_push_pull_baseline"
BASELINE_NAME = "Crypto Push-Pull Baseline"


def ensure_crypto_push_pull_baseline(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    """
    Paper-only push-pull strategy for USD-funded crypto pairs.
    Does not enable live trading.
    """
    cfg = config or ConfigManager(session).get_current()
    cpp = dict(cfg.get("crypto_push_pull") or {})
    params = {
        "stop_loss_pct": float(cpp.get("stop_loss_pct", 0.02)),
        "take_profit_pct": float(cpp.get("take_profit_pct", 0.03)),
        "max_hold_hours": float(cpp.get("max_hold_hours", 12)),
        "momentum_threshold_1h": float(cpp.get("momentum_threshold_1h", 0.004)),
        "edge_min_over_cost": float(cpp.get("edge_min_over_cost", 1.2)),
        "push_pull_mode": "paper_experiment",
    }
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"]

    reg = session.exec(
        select(StrategyRegistry).where(StrategyRegistry.strategy_id == BASELINE_ID)
    ).first()

    if not reg:
        reg = StrategyRegistry(
            strategy_id=BASELINE_ID,
            name=BASELINE_NAME,
            family="crypto_push_pull",
            asset_class="crypto",
            symbols=symbols,
            timeframe="5Min",
            parameter_schema_json=params,
            active_parameters_json=params,
            current_stage="paper_experiment",
            can_trade_paper=True,
            can_trade_live=False,
            live_locked=True,
            quarantine_status=None,
        )
        session.add(reg)
        created = True
    else:
        reg.name = BASELINE_NAME
        reg.family = "crypto_push_pull"
        reg.asset_class = "crypto"
        reg.symbols = symbols
        reg.timeframe = "5Min"
        reg.active_parameters_json = params
        reg.parameter_schema_json = params
        reg.current_stage = "paper_experiment"
        reg.can_trade_paper = True
        reg.can_trade_live = False
        reg.live_locked = True
        reg.quarantine_status = None
        session.add(reg)
        created = False

    # Also elevate legacy crypto_push_pull to paper_experiment when baseline is primary
    legacy = session.exec(
        select(StrategyRegistry).where(StrategyRegistry.strategy_id == "crypto_push_pull")
    ).first()
    if legacy and legacy.current_stage in ("research_only", "rejected", "watchlist"):
        legacy.current_stage = "paper_experiment"
        legacy.can_trade_paper = True
        legacy.symbols = symbols
        legacy.active_parameters_json = params
        session.add(legacy)

    session.flush()
    return {
        "status": "ok",
        "strategy_id": BASELINE_ID,
        "created": created,
        "current_stage": "paper_experiment",
        "symbols": symbols,
    }


def strategy_eligibility_export(session: Session) -> dict[str, Any]:
    from app.services.aggressive_paper_learning_service import AggressivePaperLearningService

    scan = AggressivePaperLearningService(session).scan_experiment_eligibility()
    return {
        "status": "ok",
        "baseline": ensure_crypto_push_pull_baseline(session),
        "eligible": scan.get("eligible", []),
        "blocked": scan.get("blocked", []),
        "eligible_count": len(scan.get("eligible") or []),
        "blocked_count": len(scan.get("blocked") or []),
    }
