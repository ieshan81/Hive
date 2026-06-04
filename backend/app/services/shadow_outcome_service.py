"""Shadow outcome tracking — simulated closes; never broker or paper evidence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ShadowTrade
from app.services.engine_config import cfg_get
from app.services.shadow_league_constants import (
    LEVEL_SHADOW_TRADE,
    STATUS_CLOSED,
    STATUS_OPEN,
)
from app.services.shadow_promotion_ladder_service import ShadowPromotionLadderService
from app.services.shadow_trade_service import shadow_league_enabled


def _level_price(levels: dict[str, Any], key: str) -> Optional[float]:
    raw = levels.get(key)
    if raw is None:
        return None
    if isinstance(raw, dict):
        p = raw.get("price")
        return float(p) if p is not None else None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _pnl_bps(entry: float, exit_px: float, *, side: str = "buy") -> float:
    if entry <= 0 or exit_px <= 0:
        return 0.0
    if str(side).lower() in ("sell", "short"):
        return ((entry - exit_px) / entry) * 10000.0
    return ((exit_px - entry) / entry) * 10000.0


def _verdict_from_pnl(pnl_bps: float, *, has_prices: bool) -> str:
    if not has_prices:
        return "unknown"
    if abs(pnl_bps) < 0.5:
        return "flat"
    if pnl_bps > 0:
        return "win"
    return "loss"


def _hold_seconds(row: ShadowTrade, now: datetime) -> float:
    opened = row.created_at
    if not opened:
        return 0.0
    if opened.tzinfo:
        opened = opened.replace(tzinfo=None)
    return max(0.0, (now - opened).total_seconds())


class ShadowOutcomeService:
    """Update open shadow trades using reference prices only (no Alpaca / paper execution)."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def _shadow_cfg(self) -> dict[str, Any]:
        return self.config.get("shadow_league") or {}

    def update_open_trades(self, *, price_by_symbol: Optional[dict[str, float]] = None) -> dict[str, Any]:
        if not shadow_league_enabled(self.config):
            return {"status": "disabled", "updated": 0}

        sl = self._shadow_cfg()
        max_hold_h = float(sl.get("max_hold_hours", cfg_get(self.config, "shadow_league.max_hold_hours", 8)))
        min_hold_s = float(sl.get("min_hold_seconds", cfg_get(self.config, "shadow_league.min_hold_seconds", 90)))
        win_bps = float(sl.get("win_threshold_bps", cfg_get(self.config, "shadow_league.win_threshold_bps", 5)))
        loss_bps = float(sl.get("loss_threshold_bps", cfg_get(self.config, "shadow_league.loss_threshold_bps", -5)))
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=max_hold_h)
        price_by_symbol = price_by_symbol or {}

        rows = list(
            self.session.exec(
                select(ShadowTrade).where(
                    ShadowTrade.status == STATUS_OPEN,
                    ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
                )
            ).all()
        )
        closed = 0
        close_reason_counts: dict[str, int] = {}

        for row in rows:
            close = self._evaluate_close(
                row,
                price_by_symbol=price_by_symbol,
                now=now,
                cutoff=cutoff,
                min_hold_s=min_hold_s,
                win_bps=win_bps,
                loss_bps=loss_bps,
            )
            if not close:
                continue
            reason = close["exit_reason"]
            close_reason_counts[reason] = close_reason_counts.get(reason, 0) + 1
            row.status = STATUS_CLOSED
            row.closed_at = now
            row.updated_at = now
            row.entry_reference_price = close.get("entry_price") or row.entry_reference_price
            row.exit_reference_price = close["exit_price"]
            row.simulated_pnl_bps = round(close["pnl_bps"], 2)
            row.outcome_verdict = close["verdict"]
            row.outcome_json = {
                "verdict": close["verdict"],
                "exit_reason": reason,
                "exit_reference_price": close["exit_price"],
                "entry_reference_price": row.entry_reference_price,
                "opened_at": row.created_at.isoformat() + "Z" if row.created_at else None,
                "closed_at": row.closed_at.isoformat() + "Z",
                "simulated_pnl_bps": row.simulated_pnl_bps,
                "hold_seconds": round(close.get("hold_seconds") or 0, 1),
                "counts_as_broker_evidence": False,
            }
            row.counts_as_broker_evidence = False
            self.session.add(row)
            closed += 1

        if closed:
            self.session.commit()
            ShadowPromotionLadderService(self.session, self.config).reevaluate_all()

        return {
            "status": "ok",
            "open_scanned": len(rows),
            "closed": closed,
            "close_reason_counts": close_reason_counts,
        }

    def release_oldest_open_if_at_cap(self, run_id: str) -> int:
        """Close oldest open L1 trades when at max_open_shadow_trades so new setups are not stuck."""
        sl = self._shadow_cfg()
        cap = int(sl.get("max_open_shadow_trades", cfg_get(self.config, "shadow_league.max_open_shadow_trades", 20)))
        open_rows = list(
            self.session.exec(
                select(ShadowTrade).where(
                    ShadowTrade.validation_run_id == run_id,
                    ShadowTrade.status == STATUS_OPEN,
                    ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
                )
                .order_by(ShadowTrade.created_at.asc())
            ).all()
        )
        if len(open_rows) < cap:
            return 0
        excess = len(open_rows) - cap + 1
        released = 0
        for row in open_rows[:excess]:
            close = self._evaluate_close(
                row,
                price_by_symbol={},
                now=datetime.utcnow(),
                cutoff=datetime.utcnow(),
                min_hold_s=0.0,
                win_bps=5.0,
                loss_bps=-5.0,
                force_reason="max_open_cap_release",
            )
            if not close:
                close = {
                    "exit_reason": "max_open_cap_release",
                    "exit_price": row.entry_reference_price or 0.0,
                    "entry_price": row.entry_reference_price,
                    "pnl_bps": 0.0,
                    "verdict": "flat",
                    "hold_seconds": _hold_seconds(row, datetime.utcnow()),
                }
            row.status = STATUS_CLOSED
            row.closed_at = datetime.utcnow()
            row.exit_reference_price = close["exit_price"]
            row.simulated_pnl_bps = round(close["pnl_bps"], 2)
            row.outcome_verdict = close["verdict"]
            row.outcome_json = {
                "verdict": close["verdict"],
                "exit_reason": close["exit_reason"],
                "entry_reference_price": row.entry_reference_price,
                "exit_reference_price": row.exit_reference_price,
                "opened_at": row.created_at.isoformat() + "Z" if row.created_at else None,
                "closed_at": row.closed_at.isoformat() + "Z",
                "simulated_pnl_bps": row.simulated_pnl_bps,
                "counts_as_broker_evidence": False,
            }
            self.session.add(row)
            released += 1
        if released:
            self.session.commit()
        return released

    def _evaluate_close(
        self,
        row: ShadowTrade,
        *,
        price_by_symbol: dict[str, float],
        now: datetime,
        cutoff: datetime,
        min_hold_s: float,
        win_bps: float,
        loss_bps: float,
        force_reason: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        sym = row.symbol
        px = price_by_symbol.get(sym)
        entry = row.entry_reference_price
        if entry is None:
            ev = row.evidence_json or {}
            entry = _level_price(ev.get("dynamic_exit_levels") or {}, "entry_price")
        if entry is None and px is not None:
            entry = px
            row.entry_reference_price = entry

        hold_s = _hold_seconds(row, now)
        if force_reason:
            if not entry or not px:
                return {
                    "exit_reason": force_reason,
                    "exit_price": px or entry or 0.0,
                    "entry_price": entry,
                    "pnl_bps": 0.0,
                    "verdict": "flat",
                    "hold_seconds": hold_s,
                }
            pnl = _pnl_bps(entry, px, side=row.side or "buy")
            return {
                "exit_reason": force_reason,
                "exit_price": px,
                "entry_price": entry,
                "pnl_bps": pnl,
                "verdict": _verdict_from_pnl(pnl, has_prices=True),
                "hold_seconds": hold_s,
            }

        if px is None or px <= 0:
            if hold_s >= min_hold_s and entry:
                return {
                    "exit_reason": "missing_price_data",
                    "exit_price": entry,
                    "entry_price": entry,
                    "pnl_bps": 0.0,
                    "verdict": "unknown",
                    "hold_seconds": hold_s,
                }
            return None

        if hold_s < min_hold_s:
            return None

        levels = (row.evidence_json or {}).get("dynamic_exit_levels") or {}
        if not isinstance(levels, dict):
            levels = {}
        stop = _level_price(levels, "stop_loss")
        target = _level_price(levels, "take_profit")
        trail = _level_price(levels, "trailing_stop")
        invalidation = _level_price(levels, "invalidation_price")
        entry = entry or _level_price(levels, "entry_price") or px
        if entry <= 0:
            return {
                "exit_reason": "missing_entry_price",
                "exit_price": px,
                "entry_price": None,
                "pnl_bps": 0.0,
                "verdict": "unknown",
                "hold_seconds": hold_s,
            }

        side = row.side or "buy"
        exit_px = px
        exit_reason: Optional[str] = None

        if target and px >= target:
            exit_px = target
            exit_reason = "shadow_target"
        elif stop and px <= stop:
            exit_px = stop
            exit_reason = "shadow_stop"
        elif trail and px <= trail:
            exit_px = trail
            exit_reason = "shadow_trailing_stop"
        elif invalidation and px <= invalidation:
            exit_px = invalidation
            exit_reason = "shadow_invalidation"
        else:
            rev = float((row.evidence_json or {}).get("reversal_risk_score") or 0)
            if rev >= 0.85 and hold_s >= min_hold_s * 2:
                exit_reason = "shadow_reversal_risk"
                exit_px = px
            elif row.created_at and row.created_at.replace(tzinfo=None) < cutoff:
                exit_reason = "shadow_max_hold"
                exit_px = px

        if not exit_reason:
            return None

        pnl = _pnl_bps(entry, exit_px, side=side)
        verdict = _verdict_from_pnl(pnl, has_prices=True)
        if exit_reason == "shadow_max_hold":
            if pnl > win_bps:
                verdict = "win"
            elif pnl < loss_bps:
                verdict = "loss"
            else:
                verdict = "flat"

        return {
            "exit_reason": exit_reason,
            "exit_price": exit_px,
            "entry_price": entry,
            "pnl_bps": pnl,
            "verdict": verdict,
            "hold_seconds": hold_s,
        }
