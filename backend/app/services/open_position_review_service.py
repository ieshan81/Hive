"""Review open positions for stale push-pull / meme hold violations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot, StrategySignal
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.config_manager import ConfigManager
from app.services.lesson_memory_service import LessonMemoryService
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector
from app.services.position_hold_time_service import build_position_truth, resolve_entry_time


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

        truth = build_position_truth(self.session, symbol, pos)
        hold = resolve_entry_time(self.session, symbol, pos=pos)
        tier = AggressivePaperLearningService(self.session).symbol_tier(symbol)
        strategy = truth.get("strategy_name")
        signal_id = truth.get("signal_id")
        intent = self._strategy_intent(strategy, signal_id)

        push_pull_max = int(
            self.pl_cfg.get("push_pull_max_hold_minutes")
            or self.config.get("crypto_push_pull", {}).get("max_hold_hours", 0.5) * 60
            or 30
        )
        max_hold = int(self.pl_cfg.get("meme_coin_max_hold_minutes", 240))
        if tier == "MAJOR_CRYPTO":
            max_hold = int(self.pl_cfg.get("major_crypto_max_hold_hours", 48)) * 60
        effective_max = push_pull_max if intent == "quick_push_pull" else max_hold

        true_hold = float(hold.get("true_hold_minutes") or 0)
        stale = intent == "quick_push_pull" and true_hold > effective_max
        if tier == "MEME_SUPPORTED" and intent == "quick_push_pull" and true_hold > effective_max:
            stale = True

        action = "hold"
        reason = "within_hold_window"
        stale_status = "active"
        if stale:
            action = "exit_recommended"
            reason = f"exceeded_quick_push_max_hold_{effective_max}m"
            stale_status = "stale"
            self._stale_memory(symbol, strategy, true_hold, effective_max, pos)
        elif true_hold > effective_max * 0.8 and tier == "MEME_SUPPORTED" and intent == "quick_push_pull":
            action = "tighten_stop"
            reason = "approaching_max_hold"
            stale_status = "warning"

        spike = MemeVolatilitySpikeDetector(self.session, self.config).evaluate_symbol(symbol)
        return {
            **truth,
            **hold,
            "tier": tier,
            "strategy": strategy,
            "intent": intent,
            "hold_minutes": true_hold,
            "true_hold_minutes": true_hold,
            "max_hold_minutes": effective_max,
            "push_pull_max_hold_minutes": push_pull_max,
            "stale": stale,
            "stale_status": stale_status,
            "action": action,
            "reason": reason,
            "exit_status": truth.get("exit_status", "open"),
            "monitor_status": truth.get("monitor_status", "active"),
            "manipulation_risk": spike.get("manipulation_risk"),
            "broker_mode": "paper",
            "live_trading_locked": True,
            "reviewed_at": datetime.utcnow().isoformat() + "Z",
        }

    def _strategy_intent(self, strategy: Optional[str], signal_id: Optional[int]) -> str:
        if strategy and "push" in str(strategy).lower():
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
                f"Open {symbol} true hold {hold_min:.0f}m (from order fill) exceeds quick push-pull max {max_hold}m. "
                "Do not let training positions become passive bags."
            ),
            detailed_lesson=(
                "Meme push-pull requires fast exit discipline. true_hold_minutes uses filled_at, not broker sync."
            ),
            symbol=symbol,
            strategy_name=strategy,
            source="open_position_review",
            pattern_key=f"stale|{symbol}|{datetime.utcnow().date()}",
            can_influence_ranking=False,
            visible_to_ai=True,
        )
