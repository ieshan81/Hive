"""Config manager — database-backed, no hard-coded strategy settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import ConfigCurrent, ConfigHistory
from app.services.default_config import DEFAULT_CONFIG


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_locked_caps(proposed: dict) -> dict:
    locked = proposed.get("locked_safety_caps", DEFAULT_CONFIG["locked_safety_caps"])
    result = dict(proposed)
    for key, cap in locked.items():
        if key in result:
            if isinstance(cap, bool):
                if key == "live_trading_enabled" and cap is False:
                    result[key] = False
            elif isinstance(cap, (int, float)) and isinstance(result.get(key), (int, float)):
                if key.startswith("max_"):
                    result[key] = min(result[key], cap)
                else:
                    result[key] = max(result[key], cap) if "limit" in key else min(result[key], cap)
    result["live_trading_enabled"] = False
    result["paper_trading_only"] = True
    return result


def _dynamic_formula_paper_patch() -> dict:
    """Migrate existing DB configs away from legacy fixed paper caps.

    This intentionally does not enable paper orders or the scheduler. It only
    changes caps and cached-universe behavior when the operator already enables
    paper learning.
    """
    return {
        "max_position_size_pct": 1.0,
        "max_open_positions": 0,
        "portfolio": {
            "max_concurrent_positions": 0,
            "max_total_exposure_pct": 100.0,
            "reserve_cash_pct": 5.0,
        },
        "execution": {
            "max_orders_per_cycle": 0,
            "max_orders_per_hour": 0,
            "max_orders_per_day": 0,
        },
        "risk": {
            "max_exposure_per_symbol_pct": 100.0,
            "max_total_crypto_exposure_pct": 100.0,
            "emergency_cash_floor_pct": 5.0,
        },
        "universe": {
            "mode": "hybrid_radar",
            "max_execution_shortlist": 0,
            "require_1m_fresh_for_shortlist": False,
            "allow_zero_volume_cached_bars_for_paper": True,
            "speculative_paper_exploration": True,
        },
        "exploration": {
            "enabled": True,
            "max_trade_notional_usd": 0.0,
            "max_positions": 0,
            "dynamic_formula_mode": True,
        },
        "aggressive_paper_learning": {
            "max_experiment_notional_per_trade_usd": 0,
            "max_experiment_positions_total": 0,
            "max_experiment_trades_per_day": 0,
            "max_experiment_trades_per_strategy_per_day": 0,
            "max_open_experiment_positions": 0,
            "use_capital_allocator": True,
        },
        "autonomous_paper_learning": {
            "max_paper_trades_per_day": 0,
            "max_paper_notional_per_trade_usd": 0,
            "max_open_paper_positions": 0,
            "max_rejected_orders_per_day": 0,
            "use_capital_allocator": True,
        },
        "capital_allocator": {
            "cash_reserve_weight": 0.05,
            "min_cash_reserve": 1,
            "crypto_night_reserve_weight": 0.35,
            "max_single_stock_exposure_weight": 0.95,
            "max_single_crypto_exposure_weight": 0.95,
            "max_asset_class_exposure_weight": 1.0,
            "operator_emergency_max_open_positions": 0,
            "min_trade_notional_usd": 1,
        },
        "fast_training": {
            "fast_training_max_trades_per_day": 0,
            "fast_training_max_open_positions": 0,
        },
    }


def _quick_scalp_structure_patch() -> dict:
    """V7 paper profile: faster dynamic exits and no bearish long probes."""

    return {
        "push_pull": {
            "dynamic_exits": {
                "quick_scalp_enabled": True,
                "base_target_r_multiple": 0.9,
                "max_target_r_multiple": 1.8,
                "profit_target_bps": 120.0,
                "min_target_bps_major": 55.0,
                "min_target_bps_alt": 80.0,
                "min_target_bps_meme": 100.0,
                "target_spread_multiplier": 4.0,
                "max_quick_target_bps": 180.0,
                "trailing_giveback_bps": 45.0,
            },
            "long_structure": {
                "enabled": True,
                "min_bullish_pattern_confidence": 0.45,
                "max_negative_momentum_without_pattern": -0.0005,
            },
        },
    }


class ConfigManager:
    def __init__(self, session: Session):
        self.session = session

    def get_current(self) -> dict:
        row = self.session.get(ConfigCurrent, 1)
        if row is None:
            self._activate(DEFAULT_CONFIG, changed_by="system", reason="Initial default config")
            row = self.session.get(ConfigCurrent, 1)
        if row is None:
            return DEFAULT_CONFIG
        row_config = row.config_json or {}
        row_version = int(row_config.get("config_version", 0) or 0)
        merged = _deep_merge(DEFAULT_CONFIG, row_config)
        if row_version < DEFAULT_CONFIG.get("config_version", 1):
            if row_version < 4:
                merged = _deep_merge(merged, _dynamic_formula_paper_patch())
            if row_version < 7:
                merged = _deep_merge(merged, _quick_scalp_structure_patch())
            merged["config_version"] = DEFAULT_CONFIG["config_version"]
            self._activate(merged, changed_by="system", reason="Migrate config to dynamic formula paper profile")
            merged = self.get_current()
        # Migrate legacy curated default → hybrid radar (production safety: debug mode still available).
        uni = merged.get("universe") or {}
        if str(uni.get("mode", "")).lower() in ("curated_watchlist", "curated", ""):
            patch = {
                "universe": DEFAULT_CONFIG.get("universe"),
                "exploration": DEFAULT_CONFIG.get("exploration"),
            }
            merged = _deep_merge(merged, patch)
            row = self._activate(merged, changed_by="system", reason="Migrate universe.mode to hybrid_radar")
            return _apply_locked_caps(row.config_json)
        return _apply_locked_caps(merged)

    def get_current_readonly(self) -> dict:
        """PURE READ of the effective config — same result as get_current() but NEVER migrates or
        writes/commits. Use on read-only/status/diagnostic paths so a read cannot mutate config.
        Locked caps are still applied (live stays false / paper true); explicit migration happens
        only via get_current()/_activate()."""
        row = self.session.get(ConfigCurrent, 1)
        if row is None:
            return _apply_locked_caps(_deep_merge(DEFAULT_CONFIG, {}))
        row_config = row.config_json or {}
        merged = _deep_merge(DEFAULT_CONFIG, row_config)
        # Apply migration patches IN MEMORY only (never persisted here).
        row_version = int(row_config.get("config_version", 0) or 0)
        if row_version < DEFAULT_CONFIG.get("config_version", 1):
            if row_version < 4:
                merged = _deep_merge(merged, _dynamic_formula_paper_patch())
            if row_version < 7:
                merged = _deep_merge(merged, _quick_scalp_structure_patch())
            merged["config_version"] = DEFAULT_CONFIG["config_version"]
        uni = merged.get("universe") or {}
        if str(uni.get("mode", "")).lower() in ("curated_watchlist", "curated", ""):
            merged = _deep_merge(
                merged,
                {"universe": DEFAULT_CONFIG.get("universe"), "exploration": DEFAULT_CONFIG.get("exploration")},
            )
        return _apply_locked_caps(merged)

    def _activate(self, config: dict, changed_by: str, reason: str) -> ConfigCurrent:
        safe = _apply_locked_caps(config)
        current = self.session.get(ConfigCurrent, 1)
        version = 1 if current is None else current.version + 1
        if current is None:
            current = ConfigCurrent(id=1, config_json=safe, version=version)
            self.session.add(current)
        else:
            current.config_json = safe
            current.version = version
            current.activated_at = datetime.utcnow()
            self.session.add(current)
        history = ConfigHistory(
            config_json=safe,
            status="active",
            reason=reason,
            changed_by=changed_by,
            activated_at=datetime.utcnow(),
        )
        self.session.add(history)
        self.session.commit()
        self.session.refresh(current)
        return current

    def propose(self, proposed: dict, changed_by: str, reason: str) -> ConfigHistory:
        current = self.get_current()
        merged = _deep_merge(current, proposed)
        safe = _apply_locked_caps(merged)
        diff = {k: safe[k] for k in safe if current.get(k) != safe[k]}
        row = ConfigHistory(
            config_json=safe,
            status="proposed",
            reason=reason,
            changed_by=changed_by,
            diff=diff,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def activate_proposal(self, proposal_id: int) -> ConfigCurrent:
        proposal = self.session.get(ConfigHistory, proposal_id)
        if proposal is None or proposal.status != "proposed":
            raise ValueError("Proposal not found or not in proposed state")
        proposal.status = "active"
        proposal.activated_at = datetime.utcnow()
        self.session.add(proposal)
        return self._activate(proposal.config_json, proposal.changed_by, proposal.reason or "Activated proposal")

    def reject_proposal(self, proposal_id: int, reason: str) -> ConfigHistory:
        proposal = self.session.get(ConfigHistory, proposal_id)
        if proposal is None:
            raise ValueError("Proposal not found")
        proposal.status = "rejected"
        proposal.reason = reason
        self.session.add(proposal)
        self.session.commit()
        self.session.refresh(proposal)
        return proposal

    def rollback(self, history_id: int) -> ConfigCurrent:
        row = self.session.get(ConfigHistory, history_id)
        if row is None:
            raise ValueError("Config history entry not found")
        return self._activate(row.config_json, "system", f"Rollback to history {history_id}")

    def list_history(self, limit: int = 50) -> list[ConfigHistory]:
        return list(
            self.session.exec(
                select(ConfigHistory).order_by(ConfigHistory.created_at.desc()).limit(limit)
            ).all()
        )

    def config_diff(self, proposal_id: int) -> dict[str, Any]:
        proposal = self.session.get(ConfigHistory, proposal_id)
        if proposal is None:
            return {}
        return proposal.diff or {}
