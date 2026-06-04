"""Per-tick shadow league diagnostics — measurable zero reasons and near-misses."""

from __future__ import annotations

from typing import Any, Optional

from app.services.shadow_floor_utils import quality_on_shadow_scale, shadow_floors_from_config
from app.services.shadow_trade_service import shadow_league_enabled


def classify_zero_shadow_tick_reason(
    *,
    rows_scored: int,
    rows_above_observation_floor: int,
    shadow_observations_created: int,
    shadow_errors: int,
    shadow_disabled: bool,
    validation_run_missing: bool,
) -> Optional[str]:
    if shadow_disabled:
        return "shadow_disabled"
    if validation_run_missing:
        return "validation_run_missing"
    if shadow_errors:
        return "exception"
    if rows_scored == 0:
        return "no_rows_scored"
    if rows_above_observation_floor == 0:
        return "quality_below_observation_floor"
    if shadow_observations_created == 0:
        return "write_failed"
    return None


def build_shadow_tick_diagnostics(
    config: dict[str, Any],
    *,
    rows_scored: int,
    rows_above_observation_floor: int,
    rows_above_shadow_floor: int,
    max_setup_quality: float,
    quality_scale: str,
    shadow_attempts: int,
    shadow_observations_created: int,
    shadow_trades_created: int,
    shadow_errors: int,
    near_misses: list[dict[str, Any]],
    skip_reason_counts: dict[str, int],
) -> dict[str, Any]:
    obs_01, trade_01, _ = shadow_floors_from_config(config)
    obs_floor = obs_01 * 100.0 if quality_scale == "0_100" else obs_01
    shadow_floor = trade_01 * 100.0 if quality_scale == "0_100" else trade_01
    zero_reason = classify_zero_shadow_tick_reason(
        rows_scored=rows_scored,
        rows_above_observation_floor=rows_above_observation_floor,
        shadow_observations_created=shadow_observations_created,
        shadow_errors=shadow_errors,
        shadow_disabled=not shadow_league_enabled(config),
        validation_run_missing=False,
    )
    return {
        "observation_floor": round(obs_floor, 4),
        "shadow_floor": round(shadow_floor, 4),
        "observation_floor_config_0_1": obs_01,
        "shadow_floor_config_0_1": trade_01,
        "quality_scale": quality_scale,
        "max_setup_quality_last_tick": round(max_setup_quality, 4) if rows_scored else None,
        "rows_scored_last_tick": rows_scored,
        "rows_above_observation_floor": rows_above_observation_floor,
        "rows_above_shadow_floor": rows_above_shadow_floor,
        "last_tick_shadow_attempts": shadow_attempts,
        "last_tick_shadow_observations_created": shadow_observations_created,
        "last_tick_shadow_trades_created": shadow_trades_created,
        "last_tick_shadow_errors": shadow_errors,
        "last_tick_zero_shadow_reason": zero_reason,
        "skip_reason_counts": skip_reason_counts,
        "near_misses_top_10": near_misses[:10],
        "push_pull_shadow_observer_ran": True,
        "note": "Shadow pass scores all ranked setups; paper path remains entry_allowed-only.",
    }


def record_near_miss(
    near_misses: list[dict[str, Any]],
    *,
    symbol: str,
    quality: float,
    obs_floor: float,
    shadow_floor: float,
    blocker: str,
    shadow_skip_reason: str,
) -> None:
    gap_obs = round(max(0.0, obs_floor - quality), 4)
    gap_shadow = round(max(0.0, shadow_floor - quality), 4)
    near_misses.append(
        {
            "symbol": symbol,
            "quality": round(quality, 4),
            "observation_floor": round(obs_floor, 4),
            "shadow_floor": round(shadow_floor, 4),
            "floor_gap_observation": gap_obs,
            "floor_gap_shadow": gap_shadow,
            "blocker": blocker,
            "shadow_skip_reason": shadow_skip_reason,
        }
    )
