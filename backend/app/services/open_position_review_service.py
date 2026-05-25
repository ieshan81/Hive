"""Review open positions for stale push-pull / meme hold violations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import OrderRecord, PositionEnrichedState, PositionSnapshot, StrategySignal
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.config_manager import ConfigManager
from app.services.lesson_memory_service import LessonMemoryService
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector


class OpenPositionReviewService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.pl_cfg = AggressivePaperLearningService(session).cfg
        self.lessons = LessonMemoryService(session, self.config)

    def review_all(self) -> dict[str, Any]:
        reviews = []
        for pos in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            reviews.append(self.review_position(pos.symbol, pos))
        return {"status": "ok", "reviews": reviews, "count": len(reviews)}

    def review_position(self, symbol: str, pos: Optional[PositionSnapshot] = None) -> dict[str, Any]:
        if pos is None:
            pos = self.session.exec(
                select(PositionSnapshot).where(PositionSnapshot.symbol == symbol, PositionSnapshot.qty > 0)
            ).first()
        if not pos:
            return {"symbol": symbol, "status": "no_position"}

        tier = AggressivePaperLearningService(self.session).symbol_tier(symbol)
        hold_min = self._hold_minutes(pos)
        max_hold = int(self.pl_cfg.get("meme_coin_max_hold_minutes", 240))
        if tier == "MAJOR_CRYPTO":
            max_hold = int(self.pl_cfg.get("major_crypto_max_hold_hours", 48)) * 60

        norm_sym = symbol.replace("/", "")
        enriched = self.session.exec(
            select(PositionEnrichedState).where(
                PositionEnrichedState.broker_symbol.in_([symbol, norm_sym, f"{norm_sym}USD"])
            )
        ).first()
        state = (enriched.state_json or {}) if enriched else {}
        strategy = state.get("strategy") or state.get("strategy_id")
        signal_id = state.get("signal_id")
        intent = self._strategy_intent(strategy, signal_id)

        stale = tier == "MEME_SUPPORTED" and intent == "quick_push_pull" and hold_min > max_hold
        action = "hold"
        reason = "within_hold_window"
        if stale:
            action = "exit_recommended"
            reason = f"exceeded_quick_push_max_hold_{max_hold}m"
            self._stale_memory(symbol, strategy, hold_min, max_hold, pos)
        elif hold_min > max_hold * 0.8 and tier == "MEME_SUPPORTED":
            action = "tighten_stop"
            reason = "approaching_max_hold"

        spike = MemeVolatilitySpikeDetector(self.session, self.config).evaluate_symbol(symbol)
        return {
            "symbol": symbol,
            "tier": tier,
            "strategy": strategy,
            "signal_id": signal_id,
            "intent": intent,
            "hold_minutes": hold_min,
            "max_hold_minutes": max_hold,
            "qty": pos.qty,
            "unrealized_pl": getattr(pos, "unrealized_pl", None),
            "stale": stale,
            "action": action,
            "reason": reason,
            "manipulation_risk": spike.get("manipulation_risk"),
            "broker_mode": "paper",
            "live_trading_locked": True,
        }

    def _hold_minutes(self, pos: PositionSnapshot) -> float:
        opened = getattr(pos, "synced_at", None)
        if not opened:
            order = self.session.exec(
                select(OrderRecord).where(OrderRecord.symbol == pos.symbol).order_by(OrderRecord.created_at.desc())
            ).first()
            opened = order.created_at if order else datetime.utcnow() - timedelta(hours=1)
        return max(0.0, (datetime.utcnow() - opened).total_seconds() / 60.0)

    def _strategy_intent(self, strategy: Optional[str], signal_id: Optional[int]) -> str:
        if strategy and "push" in strategy.lower():
            return "quick_push_pull"
        if signal_id:
            sig = self.session.get(StrategySignal, signal_id)
            if sig and "push" in (sig.strategy or "").lower():
                return "quick_push_pull"
        return "standard"

    def _stale_memory(
        self, symbol: str, strategy: Optional[str], hold_min: float, max_hold: int, pos: PositionSnapshot
    ) -> None:
        self.lessons.upsert_lesson(
            memory_type="stale_position_memory",
            title=f"Stale push-pull: {symbol}",
            summary=(
                f"Open {symbol} held {hold_min:.0f}m exceeds quick push-pull max {max_hold}m. "
                "Do not let training positions become passive bags."
            ),
            detailed_lesson=(
                "Meme push-pull requires fast exit discipline. Route exit through caged training path when rules fire."
            ),
            symbol=symbol,
            strategy_name=strategy,
            source="open_position_review",
            pattern_key=f"stale|{symbol}|{datetime.utcnow().date()}",
            can_influence_ranking=False,
            visible_to_ai=True,
        )
