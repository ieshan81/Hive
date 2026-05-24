"""Read nested DB config with promotion-stage overrides — no hard-coded thresholds in logic."""

from __future__ import annotations

from typing import Any


def cfg_get(config: dict, path: str, default: Any = None) -> Any:
    cur: Any = config
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def current_promotion_stage(config: dict) -> str:
    return str(cfg_get(config, "promotion.current_stage", "PAPER")).upper()


def stage_params(config: dict) -> dict:
    """Merge promotion stage overrides onto base portfolio/risk/execution settings."""
    stage = current_promotion_stage(config)
    base = cfg_get(config, "promotion.stages", {}) or {}
    overrides = base.get(stage, {}) if isinstance(base, dict) else {}
    return overrides if isinstance(overrides, dict) else {}


def effective(config: dict, section: str, key: str, default: Any = None) -> Any:
    """section.key with stage override: promotion.stages.PAPER.portfolio.execute_top_n_signals style."""
    stage = current_promotion_stage(config)
    stage_block = cfg_get(config, f"promotion.stages.{stage}", {}) or {}
    if isinstance(stage_block, dict):
        sec = stage_block.get(section)
        if isinstance(sec, dict) and key in sec:
            return sec[key]
    return cfg_get(config, f"{section}.{key}", default)


def edge_multiplier(config: dict) -> float:
    stage = current_promotion_stage(config)
    key = f"edge_multiplier_{stage.lower()}"
    val = cfg_get(config, f"cost.{key}", None)
    if val is not None:
        return float(val)
    return float(cfg_get(config, "cost.edge_multiplier_paper", 2.0))


def risk_pct(config: dict) -> float:
    stage = current_promotion_stage(config)
    key = f"risk_pct_{stage.lower()}"
    val = effective(config, "risk", key.replace("risk_", ""), None)
    if val is None:
        val = cfg_get(config, f"risk.{key}", None)
    if val is None:
        val = cfg_get(config, "risk.risk_pct_paper", 0.5)
    return float(val) / 100.0 if float(val) > 1 else float(val)


LOCKED_CONFIG_KEYS = frozenset(
    {
        "promotion.current_stage",
        "execution.live_orders_enabled",
        "live_trading_enabled",
        "locked_safety_caps",
        "kill.manual_master_active",
    }
)
