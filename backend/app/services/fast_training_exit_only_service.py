"""Exit-only fast training — close stale/max-hold positions via caged paper path only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select, func

from app.database import OrderRecord, SettingsActionAudit
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager, _deep_merge
from app.services.engine_config import cfg_get
from app.services.lesson_memory_service import LessonMemoryService
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.paper_execution_service import PaperExecutionService
from app.services.training_execution_service import TrainingExecutionService


class FastTrainingExitOnlyService:
    """Exit-only posture: monitor + caged exits; never scan entries."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.ft = dict(self.config.get("fast_training") or {})
        self.pl = AggressivePaperLearningService(self.session)
        self.training = TrainingExecutionService(session, self.config)
        self.lessons = LessonMemoryService(session, self.config)

    def _order_count(self) -> int:
        return int(self.session.exec(select(func.count()).select_from(OrderRecord)).one())

    def status(self) -> dict[str, Any]:
        reviews = OpenPositionReviewService(self.session, self.config).review_all()
        exit_candidates = [
            r
            for r in reviews.get("reviews", [])
            if r.get("action") in ("exit_recommended", "tighten_stop") or r.get("stale")
        ]
        return {
            "status": "ok",
            "exit_only_enabled": bool(self.ft.get("exit_only_enabled", False)),
            "mode_enabled": bool(self.pl.cfg.get("mode_enabled", False)),
            "fast_training_loop_enabled": bool(self.ft.get("fast_training_loop_enabled", False)),
            "fast_training_execute_orders": bool(self.ft.get("fast_training_execute_orders", False)),
            "entries_allowed": False,
            "exit_monitor_ready": bool(self.pl.cfg.get("require_position_monitor", True)),
            "paper_broker": is_paper_broker_url(),
            "paper_orders_enabled": bool(cfg_get(self.config, "execution.paper_orders_enabled", False)),
            "live_orders_enabled": bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
            "orders_total": self._order_count(),
            "open_positions": len(reviews.get("reviews", [])),
            "exit_candidates": exit_candidates,
            "broker_path": "TrainingExecutionService→PaperExecutionService",
            **live_lock_status(self.config),
        }

    def _audit(self, action: str, operator: str, details: dict) -> None:
        self.session.add(
            SettingsActionAudit(
                action=action,
                actor=operator,
                broker_mode="paper" if is_paper_broker_url() else "unknown",
                paper_broker=is_paper_broker_url(),
                live_trading_locked=not bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
                live_orders_enabled=bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
                details_json={**details, "broker_base_url": broker_base_url(), **live_lock_status(self.config)},
            )
        )

    def _refuse(self, reason: str, operator: str) -> dict[str, Any]:
        self._audit("fast_training_exit_only_refused", operator, {"reason": reason})
        return {"status": "refused", "reason": reason, **self.status()}

    def enable(self, operator: str = "operator") -> dict[str, Any]:
        lock = live_lock_status(self.config)
        if lock.get("live_lock_status") != "locked":
            return self._refuse("live_lock_not_locked", operator)
        if not is_paper_broker_url():
            return self._refuse("broker_not_paper", operator)
        if bool(self.config.get("live_trading_enabled", False)):
            return self._refuse("live_trading_flag_set", operator)
        if not bool(cfg_get(self.config, "execution.paper_orders_enabled", False)):
            return self._refuse("paper_orders_disabled", operator)
        if not bool(self.pl.cfg.get("require_position_monitor", True)):
            return self._refuse("exit_monitor_not_ready", operator)
        pe = PaperExecutionService(self.session, self.config).status()
        if not pe.get("paper_execution_ready"):
            return self._refuse(f"paper_execution_unavailable:{pe.get('paper_execution_blockers')}", operator)

        self.pl.enable(operator)
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "fast_training": {
                    **(cur.get("fast_training") or {}),
                    "exit_only_enabled": True,
                    "fast_training_loop_enabled": True,
                    "fast_training_execute_orders": False,
                    "fast_training_require_exit_monitor": True,
                },
                "live_trading_enabled": False,
                "execution": {
                    **(cur.get("execution") or {}),
                    "live_orders_enabled": False,
                    "paper_orders_enabled": True,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "fast_training_exit_only_enable")
        self.config = cfg_mgr.get_current()
        self.ft = dict(self.config.get("fast_training") or {})
        self.pl = AggressivePaperLearningService(self.session)
        self._audit("fast_training_exit_only_enable", operator, {"exit_only_enabled": True})
        self.session.flush()
        return {"status": "ok", "message": "Exit-only mode enabled — entries disabled", **self.status()}

    def disable(self, operator: str = "operator") -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "fast_training": {
                    **(cur.get("fast_training") or {}),
                    "exit_only_enabled": False,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "fast_training_exit_only_disable")
        self.pl.disable(operator)
        self.config = cfg_mgr.get_current()
        self.ft = dict(self.config.get("fast_training") or {})
        self.pl = AggressivePaperLearningService(self.session)
        self._audit("fast_training_exit_only_disable", operator, {})
        self.session.flush()
        return {"status": "ok", "message": "Exit-only disabled", **self.status()}

    def run_exits(self, *, actor: str = "operator") -> dict[str, Any]:
        if not bool(self.ft.get("exit_only_enabled", False)):
            return {"status": "refused", "reason": "exit_only_not_enabled", **self.status()}

        orders_before = self._order_count()
        reviews = OpenPositionReviewService(self.session, self.config).review_all()
        exit_out = self.training.monitor_exits()
        stale = [r for r in reviews.get("reviews", []) if r.get("stale")]
        orders_after = self._order_count()

        for sr in stale:
            self.lessons.upsert_lesson(
                memory_type="stale_position_memory",
                title=f"Exit-only stale: {sr.get('display_symbol', sr.get('symbol'))}",
                summary=sr.get("reason", "stale position"),
                detailed_lesson=(
                    f"Exit-only run at {datetime.utcnow().isoformat()}Z. "
                    f"true_hold_minutes={sr.get('true_hold_minutes')} source={sr.get('hold_time_source')}"
                ),
                symbol=sr.get("symbol"),
                strategy_name=sr.get("strategy"),
                source="fast_training_exit_only",
                pattern_key=f"exit_only_stale|{sr.get('symbol')}|{datetime.utcnow().date()}",
            )

        return {
            "status": "ok",
            "actor": actor,
            "phases": ["open_position_review", "exit_monitor", "stale_position_check"],
            "open_position_reviews": reviews,
            "exit_monitor": exit_out,
            "stale_reviews": stale,
            "orders_before": orders_before,
            "orders_after": orders_after,
            "new_orders": max(0, orders_after - orders_before),
            "entries_blocked": True,
            "broker_path": "TrainingExecutionService→PaperExecutionService",
        }
