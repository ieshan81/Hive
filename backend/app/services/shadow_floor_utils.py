"""Shadow observation floor scale — push-pull quality is 0–100; config floors are 0–1."""

from __future__ import annotations

from typing import Any

from app.services.engine_config import cfg_get


def shadow_floors_from_config(config: dict[str, Any]) -> tuple[float, float, str]:
    """Return (observation_floor, shadow_floor, quality_scale) on the same scale as row scores."""
    sl = config.get("shadow_league") or {}
    obs_01 = float(sl.get("min_quality_for_observation", cfg_get(config, "shadow_league.min_quality_for_observation", 0.35)))
    trade_01 = float(sl.get("min_quality_for_shadow_trade", cfg_get(config, "shadow_league.min_quality_for_shadow_trade", 0.42)))
    return obs_01, trade_01, "0_1"


def quality_on_shadow_scale(quality: float, config: dict[str, Any]) -> tuple[float, float, float, str]:
    """Map row trade_quality_score and config floors to a common comparison scale."""
    obs_01, trade_01, scale = shadow_floors_from_config(config)
    q = float(quality or 0.0)
    if q > 1.0:
        return q, obs_01 * 100.0, trade_01 * 100.0, "0_100"
    return q, obs_01, trade_01, "0_1"


def classify_shadow_skip_reason(
    *,
    shadow_res: dict[str, Any],
    quality: float,
    obs_floor: float,
    row: dict[str, Any],
) -> str:
    if shadow_res.get("status") == "disabled":
        return "shadow_disabled"
    if shadow_res.get("observation"):
        return "observation_created"
    reason = str((shadow_res.get("shadow_trade") or {}).get("reason") or shadow_res.get("reason") or "")
    if reason in ("stock_shadow_disabled", "crypto_shadow_disabled"):
        return "shadow_disabled"
    if reason == "no_symbol":
        return "validation_run_missing"
    if reason in ("quality_below_shadow_floor",) or quality < obs_floor:
        return "quality_below_observation_floor"
    if row.get("bar_freshness") == "stale" or row.get("quote_freshness") == "stale":
        return "data_stale"
    if reason:
        return reason
    return "quality_below_observation_floor"
