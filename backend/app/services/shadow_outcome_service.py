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


class ShadowOutcomeService:
    """Update open shadow trades using reference prices only (no Alpaca / paper execution)."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def update_open_trades(self, *, price_by_symbol: Optional[dict[str, float]] = None) -> dict[str, Any]:
        if not shadow_league_enabled(self.config):
            return {"status": "disabled", "updated": 0}

        sl = self.config.get("shadow_league") or {}
        max_hold_h = float(sl.get("max_hold_hours", cfg_get(self.config, "shadow_league.max_hold_hours", 8)))
        cutoff = datetime.utcnow() - timedelta(hours=max_hold_h)

        rows = list(
            self.session.exec(
                select(ShadowTrade).where(
                    ShadowTrade.status == STATUS_OPEN,
                    ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
                )
            ).all()
        )
        closed = 0
        for row in rows:
            sym = row.symbol
            px = (price_by_symbol or {}).get(sym)
            if px is None:
                px = row.entry_reference_price
            if px is None:
                continue
            levels = (row.evidence_json or {}).get("dynamic_exit_levels") or {}
            stop = levels.get("stop_loss")
            target = levels.get("take_profit")
            entry = row.entry_reference_price or px
            verdict = "flat"
            pnl_bps = 0.0
            exit_px = px
            exit_reason = "mark_to_market"

            if stop is not None and px <= float(stop):
                verdict = "loss"
                exit_px = float(stop)
                exit_reason = "shadow_stop"
            elif target is not None and px >= float(target):
                verdict = "win"
                exit_px = float(target)
                exit_reason = "shadow_target"
            elif row.created_at < cutoff:
                exit_reason = "shadow_timeout"
                pnl_bps = ((px - entry) / entry * 10000.0) if entry else 0.0
                verdict = "win" if pnl_bps > 5 else ("loss" if pnl_bps < -5 else "flat")
            else:
                continue

            if verdict != "flat" or exit_reason == "shadow_timeout":
                if entry and entry > 0:
                    pnl_bps = ((exit_px - entry) / entry) * 10000.0

            row.status = STATUS_CLOSED
            row.closed_at = datetime.utcnow()
            row.updated_at = row.closed_at
            row.exit_reference_price = exit_px
            row.simulated_pnl_bps = round(pnl_bps, 2)
            row.outcome_verdict = verdict
            row.outcome_json = {
                "verdict": verdict,
                "exit_reason": exit_reason,
                "exit_reference_price": exit_px,
                "simulated_pnl_bps": row.simulated_pnl_bps,
                "counts_as_broker_evidence": False,
            }
            row.counts_as_broker_evidence = False
            self.session.add(row)
            closed += 1

        if closed:
            self.session.commit()
            ShadowPromotionLadderService(self.session, self.config).reevaluate_all()

        return {"status": "ok", "open_scanned": len(rows), "closed": closed}
