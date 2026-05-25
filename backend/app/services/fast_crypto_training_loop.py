"""Fast crypto training loop — run-once only; exits-first; caged execution path."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select, func

from app.database import OrderRecord, SystemValidationAudit
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.fast_training_lease_service import FastTrainingLeaseService
from app.services.lesson_memory_service import LessonMemoryService
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.training_execution_service import TrainingExecutionService


class FastCryptoTrainingLoop:
    """Production-safe: POST /run-once + external scheduler. No in-process Railway loop."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.ft = dict(self.config.get("fast_training") or {})
        self.pl = AggressivePaperLearningService(session)
        self.training = TrainingExecutionService(session, self.config)
        self.lessons = LessonMemoryService(session, self.config)
        self.lease = FastTrainingLeaseService(
            session,
            use_db_lease=bool(self.ft.get("use_db_lease", True)),
        )

    def _order_count(self) -> int:
        return int(self.session.exec(select(func.count()).select_from(OrderRecord)).one())

    def status(self) -> dict[str, Any]:
        pf = self.training.preflight_training()
        return {
            "status": "ok",
            "fast_training_loop_enabled": bool(self.ft.get("fast_training_loop_enabled", False)),
            "fast_training_execute_orders": bool(self.ft.get("fast_training_execute_orders", False)),
            "mode_enabled": bool(self.pl.cfg.get("mode_enabled", False)),
            "training_mode_enabled": bool(self.pl.cfg.get("mode_enabled", False)),
            "exit_monitor_ready": bool(self.pl.cfg.get("require_position_monitor", True)),
            "exit_monitor_required": bool(self.ft.get("fast_training_require_exit_monitor", True)),
            "paper_broker": is_paper_broker_url(),
            "paper_orders_enabled": bool(cfg_get(self.config, "execution.paper_orders_enabled", False)),
            "live_orders_enabled": bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
            "orders_total": self._order_count(),
            "can_submit_orders": self._can_submit_orders(),
            "blockers": self._entry_blockers(pf),
            "preflight": pf,
            "lease": self.lease.status(),
            "in_process_loop_supported": False,
            "recommended_trigger": "POST /api/fast-training/run-once",
            **live_lock_status(self.config),
        }

    def _can_submit_orders(self) -> bool:
        return (
            bool(self.ft.get("fast_training_loop_enabled"))
            and bool(self.ft.get("fast_training_execute_orders"))
            and bool(self.pl.cfg.get("mode_enabled"))
            and is_paper_broker_url()
            and bool(cfg_get(self.config, "execution.paper_orders_enabled", False))
            and not bool(cfg_get(self.config, "live_trading_enabled", False))
        )

    def _entry_blockers(self, pf: Optional[dict] = None) -> list[str]:
        blockers: list[str] = []
        if not bool(self.ft.get("fast_training_loop_enabled")):
            blockers.append("fast_training_loop_disabled")
        if not bool(self.pl.cfg.get("mode_enabled")):
            blockers.append("training_mode_disabled")
        if not bool(self.ft.get("fast_training_execute_orders")):
            blockers.append("fast_training_execute_orders_disabled")
        if bool(self.ft.get("fast_training_require_exit_monitor")) and not bool(
            self.pl.cfg.get("require_position_monitor", True)
        ):
            blockers.append("exit_monitor_unavailable")
        if pf:
            blockers.extend(pf.get("blockers") or [])
        return list(dict.fromkeys(blockers))

    def run_once(self, *, actor: str = "operator") -> dict[str, Any]:
        ok, holder = self.lease.acquire()
        if not ok:
            out = {
                "status": "blocked",
                "reason": "lease_held",
                "holder_id": holder,
                "orders_before": self._order_count(),
                "orders_after": self._order_count(),
                "new_orders": 0,
            }
            self._block_memory("lease_overlap", out)
            return out

        orders_before = self._order_count()
        result = self._execute_phases(actor=actor)
        orders_after = self._order_count()
        result["holder_id"] = holder
        result["orders_before"] = orders_before
        result["orders_after"] = orders_after
        result["new_orders"] = max(0, orders_after - orders_before)
        result["broker_path"] = "TrainingExecutionService→PaperExecutionService"
        self.lease.release(holder, result)
        self.session.add(
            SystemValidationAudit(
                actor="fast_training",
                action="run_once",
                decision=result.get("status", "unknown"),
                inputs_json={
                    "actor": actor,
                    "new_orders": result["new_orders"],
                    "phases": result.get("phases", []),
                    "blockers": result.get("blockers", []),
                },
                reasoning=(result.get("message") or "")[:500],
            )
        )
        self.session.flush()
        return result

    def _execute_phases(self, *, actor: str) -> dict[str, Any]:
        phases: list[str] = []
        pf = self.training.preflight_training()

        reviews = OpenPositionReviewService(self.session, self.config).review_all()
        phases.append("open_position_review")

        exit_out = self.training.monitor_exits()
        phases.append("exit_monitor")
        exit_ready = bool(exit_out.get("exit_monitor_ready", True))

        stale_reviews = [r for r in reviews.get("reviews", []) if r.get("stale")]
        phases.append("stale_position_check")

        blockers = self._entry_blockers(pf)
        if bool(self.ft.get("fast_training_require_exit_monitor")) and not exit_ready:
            blockers.append("exit_monitor_unavailable")

        entries_skipped = True
        entry_result: dict[str, Any] = {"status": "skipped", "reason": "entries_blocked"}

        if blockers:
            self._block_memory(
                "fast_training_blocked",
                {
                    "blockers": blockers,
                    "actor": actor,
                    "phases": phases,
                    "stale_count": len(stale_reviews),
                },
            )
            return {
                "status": "blocked",
                "message": "Fast training blocked — no entries; memory recorded",
                "blockers": blockers,
                "phases": phases,
                "open_position_reviews": reviews,
                "exit_monitor": exit_out,
                "stale_reviews": stale_reviews,
                "entries": entry_result,
                "training_mode_enabled": bool(self.pl.cfg.get("mode_enabled")),
                "fast_training_loop_enabled": bool(self.ft.get("fast_training_loop_enabled")),
                "orders_submitted": False,
            }

        phases.append("scan_entries")
        entry_result = self.training.run_training_cycle()
        entries_skipped = False
        return {
            "status": "ok",
            "message": "Fast training run-once completed (exits-first)",
            "blockers": [],
            "phases": phases,
            "open_position_reviews": reviews,
            "exit_monitor": exit_out,
            "stale_reviews": stale_reviews,
            "entries": entry_result,
            "training_mode_enabled": True,
            "fast_training_loop_enabled": True,
            "orders_submitted": bool(entry_result.get("decisions")),
        }

    def _block_memory(self, reason_code: str, details: dict) -> None:
        blockers = details.get("blockers") or [reason_code]
        self.lessons.upsert_lesson(
            memory_type="fast_training_blocked_memory",
            title="Fast training blocked",
            summary=f"Run-once blocked: {', '.join(blockers[:6])}. No broker order submitted.",
            detailed_lesson=(
                "Fast training uses exits-first ordering and TrainingExecutionService→PaperExecutionService only. "
                f"Reason: {reason_code}. Details: {details}"
            ),
            source="fast_crypto_training_loop",
            pattern_key=f"ft_blocked|{reason_code}|{datetime.utcnow().isoformat(timespec='seconds')}",
            can_influence_ranking=False,
            visible_to_ai=True,
            category="ai_learning_memory",
        )

    def start_loop(self) -> dict[str, Any]:
        return {
            "status": "not_supported",
            "message": (
                "In-process background loops are not supported on Railway. "
                "Use POST /api/fast-training/run-once with an external scheduler or Railway cron."
            ),
            "recommended": "/api/fast-training/run-once",
            "fast_training_loop_enabled": bool(self.ft.get("fast_training_loop_enabled")),
        }
