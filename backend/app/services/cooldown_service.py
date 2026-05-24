"""Deterministic cooldown checks — symbol, strategy, account."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountCooldown, SymbolCooldown, StrategyCooldown
from app.services.engine_config import cfg_get


COOLDOWN_REASONS = frozenset(
    {
        "CLOSED_LOSS",
        "CONSECUTIVE_LOSSES",
        "BROKER_REJECTION",
        "PRICE_BAND_CANCEL",
        "SPREAD_SPIKE",
        "LIQUIDITY_DROP",
        "AI_HIGH_WARNING",
        "AI_CRITICAL_WARNING",
        "ACCOUNT_LOSS_CLUSTER",
        "DAILY_DRAWDOWN",
        "WEEKLY_DRAWDOWN",
    }
)


class CooldownService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config

    def _minutes_for(self, reason: str) -> int:
        mapping = {
            "CLOSED_LOSS": "symbol_after_loss_minutes",
            "CONSECUTIVE_LOSSES": "symbol_after_two_losses_minutes",
            "BROKER_REJECTION": "broker_rejection_minutes",
            "PRICE_BAND_CANCEL": "price_band_cancel_minutes",
            "SPREAD_SPIKE": "spread_spike_minutes",
            "LIQUIDITY_DROP": "liquidity_drop_minutes",
            "AI_HIGH_WARNING": "ai_high_warning_minutes",
            "ACCOUNT_LOSS_CLUSTER": "account_three_losses_one_hour_minutes",
            "DAILY_DRAWDOWN": "daily_drawdown_minutes",
            "WEEKLY_DRAWDOWN": "weekly_drawdown_minutes",
        }
        key = mapping.get(reason, "symbol_after_loss_minutes")
        return int(cfg_get(self.config, f"cooldown.{key}", 60))

    def apply_symbol(self, symbol: str, reason: str, *, minutes: Optional[int] = None, details: Optional[dict] = None) -> SymbolCooldown:
        mins = minutes or self._minutes_for(reason)
        row = SymbolCooldown(
            symbol=symbol,
            reason=reason,
            active=True,
            expires_at=datetime.utcnow() + timedelta(minutes=mins),
            details=details or {},
        )
        self.session.add(row)
        return row

    def apply_account(self, reason: str, *, minutes: Optional[int] = None, details: Optional[dict] = None) -> AccountCooldown:
        mins = minutes or self._minutes_for(reason)
        row = AccountCooldown(
            reason=reason,
            active=True,
            expires_at=datetime.utcnow() + timedelta(minutes=mins),
            details=details or {},
        )
        self.session.add(row)
        return row

    def active_symbol(self, symbol: str) -> list[SymbolCooldown]:
        now = datetime.utcnow()
        rows = self.session.exec(
            select(SymbolCooldown)
            .where(SymbolCooldown.symbol == symbol, SymbolCooldown.active == True)  # noqa: E712
        ).all()
        return [r for r in rows if r.expires_at > now]

    def active_account(self) -> list[AccountCooldown]:
        now = datetime.utcnow()
        rows = self.session.exec(select(AccountCooldown).where(AccountCooldown.active == True)).all()  # noqa: E712
        return [r for r in rows if r.expires_at > now]

    def check_symbol(self, symbol: str) -> tuple[bool, Optional[str], Optional[dict]]:
        active = self.active_symbol(symbol)
        if active:
            r = active[0]
            return False, r.reason, {"expires_at": r.expires_at.isoformat() + "Z", "reason": r.reason}
        return True, None, None

    def check_account(self) -> tuple[bool, Optional[str], Optional[dict]]:
        active = self.active_account()
        if active:
            r = active[0]
            return False, r.reason, {"expires_at": r.expires_at.isoformat() + "Z"}
        return True, None, None

    def list_all(self) -> dict[str, Any]:
        now = datetime.utcnow()
        sym = self.session.exec(select(SymbolCooldown).where(SymbolCooldown.active == True)).all()  # noqa: E712
        acct = self.session.exec(select(AccountCooldown).where(AccountCooldown.active == True)).all()  # noqa: E712
        strat = self.session.exec(select(StrategyCooldown).where(StrategyCooldown.active == True)).all()  # noqa: E712
        def ser(rows):
            return [
                {
                    "symbol": getattr(r, "symbol", None),
                    "strategy": getattr(r, "strategy", None),
                    "reason": r.reason,
                    "expires_at": r.expires_at.isoformat() + "Z",
                    "active": r.expires_at > now,
                }
                for r in rows
                if r.expires_at > now
            ]
        return {
            "symbol_cooldowns": ser(sym),
            "strategy_cooldowns": ser(strat),
            "account_cooldowns": ser(acct),
        }
