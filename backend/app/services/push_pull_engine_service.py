"""Push-Pull Engine — scan → push → entry → pull/exit → lesson (paper only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, LessonNode, PaperExperimentDecision, SettingsActionAudit
from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
from app.services.capital_allocator import CapitalAllocatorService
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.execution_logs_query_service import scheduler_windows


OPERATOR_LABELS = {
    "daily_trade_cap": "Skipped — legacy daily cap (not active under allocator)",
    "account_pair_eligibility": "Skipped — pair needs unfunded quote currency",
    "allocator_degraded": "Blocked — broker data stale, unknown buying power",
    "allocator_blocked": "Blocked — capital allocator",
    "stale_quote": "Skipped — price data is stale",
    "no_approved_candidate": "Skipped — no push opportunity strong enough",
    "broker_not_paper": "Blocked — not paper broker",
    "paper_order_rejected": "Failed push — broker rejected entry",
    "paper_order_filled": "Entry filled — watching pull target",
}


class PushPullEngineService:
    SCHEDULER_TICK_KEY = "autonomous_scheduler"

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.allocator = CapitalAllocatorService(session, self.config)

    def status(self) -> dict[str, Any]:
        plan = self.allocator.build_plan()
        windows = scheduler_windows(self.session)
        env = env_pause_status()
        mode = plan.get("current_market_mode", "CRYPTO_NIGHT")

        stock_active = mode in ("US_STOCK_OPEN", "US_STOCK_NEAR_CLOSE", "US_STOCK_AFTER_HOURS")
        crypto_active = mode in ("CRYPTO_NIGHT", "WEEKEND_CRYPTO", "HOLIDAY_CRYPTO_ONLY", "US_STOCK_OPEN")

        return {
            "status": "ok",
            "market_mode": mode,
            "market_mode_label": _mode_label(mode),
            "stock_push_pull_active": stock_active and not env["paper_trading_paused_by_env"],
            "crypto_push_pull_active": crypto_active and not env["paper_trading_paused_by_env"],
            "analysis_only": mode == "DEGRADED_BROKER_DATA" or plan.get("status") == "degraded",
            "deployable_capital": plan.get("deployable_capital"),
            "stock_budget": plan.get("stock_hold_budget"),
            "crypto_budget": plan.get("crypto_push_pull_budget"),
            "broker_data_freshness": plan.get("broker_data_freshness"),
            "scheduler_windows": windows,
            "operator_messages": _operator_messages(mode, plan),
            "last_tick": self._last_tick_summary(),
        }

    def latest_tick(self) -> dict[str, Any]:
        return self._last_tick_summary()

    def decisions(self, limit: int = 50) -> dict[str, Any]:
        windows = scheduler_windows(self.session)
        tick_at = windows.get("last_tick_at")
        rows = list(
            self.session.exec(
                select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(200)
            ).all()
        )
        out = []
        for r in rows:
            created = r.created_at.isoformat() + "Z" if r.created_at else None
            historical = True
            if tick_at and created and created >= tick_at:
                historical = False
            out.append(
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "strategy_name": r.strategy_id,
                    "decision": r.decision,
                    "reason_code": r.reason_code,
                    "reason_plain": OPERATOR_LABELS.get(r.reason_code or "", r.reason_text or "—"),
                    "reason_text": r.reason_text,
                    "side": r.side,
                    "approved_notional": r.approved_notional,
                    "created_at": created,
                    "historical": historical,
                    "action": "Entry approved" if r.decision == "approved" else "Entry skipped",
                }
            )
        return {"status": "ok", "decisions": out[:limit], "count": len(out[:limit])}

    def lessons(self, limit: int = 40) -> dict[str, Any]:
        rows = list(
            self.session.exec(select(LessonNode).order_by(LessonNode.created_at.desc()).limit(limit)).all()
        )
        return {
            "status": "ok",
            "lessons": [
                {
                    "id": r.id,
                    "title": r.title,
                    "summary": r.summary or r.detailed_lesson,
                    "memory_type": r.memory_type,
                    "symbol": r.symbol,
                    "strategy_name": r.strategy_name,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                    "lesson_plain": _lesson_plain(r),
                }
                for r in rows
            ],
            "count": len(rows),
        }

    def export_tick_bundle(self) -> dict[str, Any]:
        windows = scheduler_windows(self.session)
        tick_at = windows.get("last_tick_at")
        decisions = self.decisions(100)
        lessons = self.lessons(50)
        logs = []
        if tick_at:
            from app.services.execution_logs_query_service import list_execution_logs

            logs = list_execution_logs(self.session, scope="latest_tick").get("execution_logs", [])
        return {
            "tick_at": tick_at,
            "windows": windows,
            "candidates_found": decisions.get("count", 0),
            "decisions": decisions.get("decisions", []),
            "lessons": lessons.get("lessons", []),
            "executions": logs,
        }

    def _last_tick_summary(self) -> dict[str, Any]:
        sched = AutonomousPaperScheduler(self.session, self.config)
        st = sched.status()
        tick_at = st.get("last_tick_at")
        if not tick_at:
            return {
                "tick_at": None,
                "result": "no_tick_yet",
                "plain": "No scheduler tick completed yet.",
                "orders_created": 0,
            }
        audit = self.session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == "autonomous_run_one_cycle")
            .order_by(SettingsActionAudit.created_at.desc())
        ).first()
        details = dict(audit.details_json or {}) if audit and audit.details_json else {}
        reason = details.get("reason") or details.get("action") or "scan_complete"
        return {
            "tick_at": tick_at,
            "result": details.get("status", "ok"),
            "plain": OPERATOR_LABELS.get(reason, f"Last tick: {reason}"),
            "orders_created": int(details.get("orders_created") or details.get("new_orders") or 0),
            "reason": reason,
        }


def _mode_label(mode: str) -> str:
    return {
        "US_STOCK_OPEN": "US stocks open — stock push-pull active",
        "US_STOCK_NEAR_CLOSE": "Near close — preserving crypto night budget",
        "US_STOCK_AFTER_HOURS": "After hours — crypto push-pull",
        "CRYPTO_NIGHT": "Crypto night — push-pull crypto",
        "WEEKEND_CRYPTO": "Weekend — crypto push-pull",
        "HOLIDAY_CRYPTO_ONLY": "Holiday — crypto only",
        "DEGRADED_BROKER_DATA": "Degraded — analysis only, no new entries",
    }.get(mode, mode)


def _operator_messages(mode: str, plan: dict) -> list[str]:
    msgs = [f"Market mode: {_mode_label(mode)}"]
    if plan.get("deployable_capital"):
        msgs.append(f"Deployable capital: ${plan.get('deployable_capital')}")
    blocked = plan.get("blocked_symbols") or []
    if blocked:
        msgs.append(f"{len(blocked)} symbols blocked before broker (quote currency / eligibility)")
    return msgs


def _lesson_plain(row: LessonNode) -> str:
    s = (row.summary or row.detailed_lesson or row.title or "")[:200]
    if "USDC" in s.upper() or "USDT" in s.upper():
        return f"{s} Avoid unfunded quote pairs unless balance exists."
    return s
