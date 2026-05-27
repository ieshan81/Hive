"""Fast crypto training loop — run-once only; exits-first; caged execution path."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select, func

from app.database import OrderRecord, PaperExperimentDecision, SettingsActionAudit, SystemValidationAudit
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager, _deep_merge
from app.services.paper_execution_service import PaperExecutionService
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
        from app.services.broker_reconciliation_service import BrokerReconciliationService

        pf = self.training.preflight_training()
        recon = BrokerReconciliationService(self.session, self.config)
        recon_blockers = recon.training_entry_blockers()
        blockers = self._entry_blockers(pf) + recon_blockers
        entries_eligible = (
            not recon_blockers
            and not any(b.startswith("open_position") for b in recon_blockers)
            and len(recon.ghost_position_candidates()) == 0
        )
        from app.services.user_facing_status import friendly_blockers, wrap_status_payload

        lease_st = self.lease.status()
        lease_meta = lease_st.get("last_result")
        stale_lease = bool(lease_meta) and not bool(self.pl.cfg.get("mode_enabled"))
        payload = {
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
            "can_submit_orders": self._can_submit_orders() and not recon_blockers,
            "blockers": list(dict.fromkeys(blockers)),
            "entries_eligible": entries_eligible,
            "entries_allowed": entries_eligible and self._can_submit_orders(),
            "broker_reconciliation": recon.doge_audit(),
            "preflight": pf,
            "lease": self.lease.status(),
            "in_process_loop_supported": False,
            "recommended_trigger": "POST /api/fast-training/run-once",
            "signals_found": entries_eligible,
            "orders_permitted": bool(self.pl.cfg.get("mode_enabled")),
            "final_can_submit_orders": entries_eligible and self._can_submit_orders(),
            "training_enabled": bool(self.pl.cfg.get("mode_enabled")),
            "live_locked": live_lock_status(self.config).get("live_lock_status") == "locked",
            "broker_reconciliation_summary": recon.doge_audit().get("classification"),
            "current_blockers_user_friendly": friendly_blockers(list(dict.fromkeys(blockers))),
            "stale_lease_warning": (
                "Last run metadata may be stale — not current open positions."
                if stale_lease
                else None
            ),
            "lease_last_result_stale": stale_lease,
            **live_lock_status(self.config),
        }
        plain = (
            "The bot found possible paper trades, but Training Mode is OFF — it cannot place orders."
            if not bool(self.pl.cfg.get("mode_enabled"))
            else (
                "Training is on and safety checks passed — operator may run once."
                if entries_eligible and self._can_submit_orders()
                else "Training is on but safety blockers prevent new orders."
            )
        )
        return wrap_status_payload(
            payload,
            plain_message=plain,
            user_facing_status="paused" if not bool(self.pl.cfg.get("mode_enabled")) else "ready_to_run_once",
            dangerous_actions=["enable_training", "run_once", "enable_exit_only"],
        )

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

    def _settings_audit(self, action: str, operator: str, details: dict) -> None:
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

    def _refuse_enable(self, reason: str, operator: str) -> dict[str, Any]:
        self._settings_audit(
            "fast_training_enable_refused",
            operator,
            {"reason": reason},
        )
        return {"status": "refused", "reason": reason, **self.status()}

    def enable(self, operator: str = "operator") -> dict[str, Any]:
        lock = live_lock_status(self.config)
        if lock.get("live_lock_status") != "locked":
            return self._refuse_enable("live_lock_not_locked", operator)
        if not is_paper_broker_url():
            return self._refuse_enable("broker_not_paper", operator)
        if bool(self.config.get("live_trading_enabled", False)):
            return self._refuse_enable("live_trading_flag_set", operator)
        if not bool(cfg_get(self.config, "execution.paper_orders_enabled", False)):
            return self._refuse_enable("paper_orders_disabled", operator)
        if not bool(self.pl.cfg.get("require_position_monitor", True)):
            return self._refuse_enable("exit_monitor_not_ready", operator)
        pe = PaperExecutionService(self.session, self.config).status()
        if not pe.get("paper_execution_ready"):
            return self._refuse_enable(
                f"paper_execution_unavailable:{pe.get('paper_execution_blockers')}",
                operator,
            )

        pl_out = self.pl.enable(operator)
        if pl_out.get("status") == "error":
            return self._refuse_enable(pl_out.get("message", "paper_learning_enable_failed"), operator)

        self.pl.update_config(
            {
                "max_experiment_trades_per_day": 0,
                "max_experiment_trades_per_strategy_per_day": 0,
                "max_open_experiment_positions": 0,
                "use_capital_allocator": True,
            }
        )

        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "fast_training": {
                    **(cur.get("fast_training") or {}),
                    "fast_training_loop_enabled": True,
                    "fast_training_execute_orders": True,
                    "fast_training_max_notional_usd": 10,
                    "fast_training_default_notional_usd": 5,
                    "fast_training_max_trades_per_day": 0,
                    "fast_training_max_open_positions": 0,
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
        cfg_mgr._activate(merged, operator, "fast_training_controlled_enable")
        self.config = cfg_mgr.get_current()
        self.ft = dict(self.config.get("fast_training") or {})
        self.pl = AggressivePaperLearningService(self.session)

        self._settings_audit(
            "fast_training_enable",
            operator,
            {
                "mode_enabled": True,
                "fast_training_loop_enabled": True,
                "fast_training_execute_orders": True,
                "max_notional_usd": 10,
                "max_trades_per_day": 1,
            },
        )
        self.session.flush()
        return {"status": "ok", "message": "Fast training enabled (controlled)", **self.status()}

    def disable(self, operator: str = "operator") -> dict[str, Any]:
        self.pl.disable(operator)
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "fast_training": {
                    **(cur.get("fast_training") or {}),
                    "fast_training_loop_enabled": False,
                    "fast_training_execute_orders": False,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "fast_training_controlled_disable")
        self.config = cfg_mgr.get_current()
        self.ft = dict(self.config.get("fast_training") or {})
        self.pl = AggressivePaperLearningService(self.session)
        self._settings_audit("fast_training_disable", operator, {"mode_enabled": False})
        self.session.flush()
        return {"status": "ok", "message": "Fast training disabled", **self.status()}

    def monitor_exits(self) -> dict[str, Any]:
        return self.training.monitor_exits()

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
        for sr in stale_reviews:
            OpenPositionReviewService(self.session, self.config).review_position(sr.get("symbol", ""))

        exit_only = bool(self.ft.get("exit_only_enabled", False))
        blockers = self._entry_blockers(pf)
        if exit_only:
            blockers.append("exit_only_mode_blocks_entries")
        if bool(self.ft.get("fast_training_require_exit_monitor")) and not exit_ready:
            blockers.append("exit_monitor_unavailable")
        if stale_reviews:
            blockers.append("stale_open_position_blocks_entry")
        open_positions = reviews.get("reviews") or []
        if open_positions and (self._can_submit_orders() or exit_only):
            blockers.append("open_position_blocks_duplicate_entry")

        entries_skipped = True
        entry_result: dict[str, Any] = {"status": "skipped", "reason": "entries_blocked"}

        from app.services.push_pull_scan_service import PushPullScanService

        score_only = PushPullScanService(self.session, self.config).run_tick_scan(max_evaluate=0)
        score_only["result"] = "entries_blocked"
        score_only["plain_summary"] = score_only.get("plain_summary") or "Scan complete — entries blocked by safety rules."

        if blockers:
            plain_block = _blocker_plain(blockers)
            score_only["plain_summary"] = (
                f"{score_only.get('plain_summary', '')} Entries blocked: {plain_block}."
            ).strip()
            score_only["entry_blockers"] = blockers
            entry_result = {
                **entry_result,
                "tick_summary": score_only,
                "reason": blockers[0],
                "message": plain_block,
            }
            self._block_memory(
                "fast_training_blocked",
                {
                    "blockers": blockers,
                    "actor": actor,
                    "phases": phases,
                    "stale_count": len(stale_reviews),
                    "exit_only": exit_only,
                },
            )
            return {
                "status": "blocked" if not exit_only else "exit_only",
                "message": f"Paper cycle blocked — {plain_block}"
                if not exit_only
                else "Exit monitor run — exits checked, new entries blocked",
                "blockers": blockers,
                "phases": phases,
                "open_position_reviews": reviews,
                "exit_monitor": exit_out,
                "stale_reviews": stale_reviews,
                "entries": entry_result,
                "tick_summary": score_only,
                "exit_only_enabled": exit_only,
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
            "tick_summary": entry_result.get("tick_summary") or score_only,
            "training_mode_enabled": True,
            "fast_training_loop_enabled": True,
            "orders_submitted": bool(entry_result.get("decisions")),
        }

    def _block_memory(self, reason_code: str, details: dict) -> None:
        blockers = sorted(details.get("blockers") or [reason_code])
        # One consolidated lesson per blocker-set — avoid spamming on every tick.
        pattern_key = "ft_blocked|" + "|".join(blockers[:8])
        summary = f"Paper cycle blocked: {', '.join(blockers[:6])}. No broker order submitted."
        self.lessons.upsert_lesson(
            memory_type="fast_training_blocked_memory",
            title="Paper cycle blocked",
            summary=summary,
            detailed_lesson=(
                "Fast training uses exits-first ordering and TrainingExecutionService→PaperExecutionService only. "
                f"Blockers: {blockers}. Details: {details}"
            ),
            source="fast_crypto_training_loop",
            pattern_key=pattern_key,
            can_influence_ranking=False,
            visible_to_ai=True,
            category="ai_learning_memory",
            aggregate=True,
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


def _blocker_plain(blockers: list[str]) -> str:
    labels = {
        "open_position_blocks_duplicate_entry": "open position already held — duplicate entry protection",
        "stale_open_position_blocks_entry": "stale open position blocks new entry",
        "data_stale": "stale bar or quote data",
        "spread_too_wide": "spread too wide",
        "no_edge_after_cost": "no edge after cost",
        "allocator_block": "allocator block",
        "training_mode_disabled": "paper learning mode off",
        "fast_training_loop_disabled": "scheduler loop disabled",
    }
    parts = [labels.get(b, b.replace("_", " ")) for b in blockers[:4]]
    return ", ".join(parts) if parts else "safety blockers active"
