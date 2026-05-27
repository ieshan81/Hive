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
        merged = _deep_merge(DEFAULT_CONFIG, row.config_json)
        if merged.get("config_version", 0) < DEFAULT_CONFIG.get("config_version", 1):
            merged["config_version"] = DEFAULT_CONFIG["config_version"]
            self._activate(merged, changed_by="system", reason="Merged default config v2")
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
