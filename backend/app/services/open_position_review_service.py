"""Review open positions for stale push-pull / meme hold violations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot, StrategySignal
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.config_manager import ConfigManager
from app.services.dynamic_exit_levels_service import compute_dynamic_exit_levels, exit_trigger_for_long
from app.services.historical_data_service import HistoricalDataService
from app.services.lesson_memory_service import LessonMemoryService
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector
from app.services.position_hold_time_service import build_position_truth, resolve_entry_time
from app.services.symbol_normalize import display_symbol, symbols_match


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
        dynamic_levels = self._dynamic_levels(symbol, pos, truth)

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
        if tier == "MEME_SUPPORTED" and true_hold >= effective_max:
            stale = True
        if intent == "quick_push_pull" and true_hold > effective_max:
            stale = True

        action = "hold"
        reason = "within_hold_window"
        stale_status = "active"
        if stale or true_hold >= effective_max:
            action = "exit_recommended"
            reason = f"exceeded_max_hold_{effective_max}m"
            stale_status = "stale"
            self._stale_memory(symbol, strategy, true_hold, effective_max, pos)
        elif true_hold >= effective_max * 0.9:
            action = "exit_recommended"
            reason = "at_or_near_max_hold"
            stale_status = "warning"
        elif true_hold > effective_max * 0.8:
            action = "tighten_stop"
            reason = "approaching_max_hold"
            stale_status = "warning"

        exit_trigger = None
        if dynamic_levels and str(pos.side or "long").lower() != "short":
            exit_trigger = exit_trigger_for_long(
                current_price=float(pos.current_price or pos.avg_entry_price or 0),
                levels=dynamic_levels,
            )
            if exit_trigger:
                action = "exit_recommended"
                reason = str(exit_trigger.get("reason") or "dynamic_exit_level_hit")
                stale_status = "exit_signal"

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
            "dynamic_exit_levels": dynamic_levels,
            "exit_trigger": exit_trigger,
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

    def _dynamic_levels(
        self, symbol: str, pos: PositionSnapshot, truth: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        sig = None
        signal_id = truth.get("signal_id")
        if signal_id:
            sig = self.session.get(StrategySignal, signal_id)
        if not sig:
            rows = list(
                self.session.exec(select(StrategySignal).order_by(StrategySignal.created_at.desc()).limit(100)).all()
            )
            sig = next((row for row in rows if symbols_match(row.symbol, symbol)), None)

        meta_raw = (sig.signal_metadata or {}) if sig else {}
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        stored = meta.get("dynamic_exit_levels") if isinstance(meta.get("dynamic_exit_levels"), dict) else None
        entry = float(pos.avg_entry_price or truth.get("avg_entry_price") or 0)
        current = float(pos.current_price or entry or 0)
        if entry <= 0:
            return stored if isinstance(stored, dict) else None

        asset_class = (getattr(sig, "asset_class", None) or ("crypto" if "/" in display_symbol(symbol) else "stock")).lower()
        hist_symbol = display_symbol(symbol) if asset_class == "crypto" else symbol
        hist = HistoricalDataService(self.session, self.config)
        bars: list[dict[str, Any]] = []
        for timeframe, lookback_days in (("1Min", 2), ("5Min", 7)):
            try:
                bars, _meta = hist.get_bars(
                    hist_symbol,
                    timeframe=timeframe,
                    min_rows=15,
                    lookback_days=lookback_days,
                    max_staleness_hours=2.0,
                    asset_class=asset_class,
                )
            except Exception:
                bars = []
            if bars:
                break

        quote = {
            "mid": current,
            "spread_pct": meta.get("spread_pct"),
        }
        signal_meta = meta.get("push_pull_score") if isinstance(meta.get("push_pull_score"), dict) else {}
        try:
            return compute_dynamic_exit_levels(
                self.config,
                symbol=hist_symbol,
                side="buy",
                entry_price=entry,
                current_price=current,
                bars=bars,
                quote=quote,
                signal_meta=signal_meta,
                tier=meta.get("tier"),
            ).to_dict()
        except Exception:
            return stored if isinstance(stored, dict) else None

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
