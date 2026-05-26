"""Honest strategy performance — no fake confidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, StrategyRegistry, TradeRecord, StrategySignal
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import get_latest_reset_epoch, record_created_after


class StrategyPerformanceService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def summary(self) -> dict[str, Any]:
        epoch = get_latest_reset_epoch(self.session)
        cutoff = epoch.get("nuke_completed_at") if epoch else None
        strategies = list(self.session.exec(select(StrategyRegistry)).all())
        rows: list[dict[str, Any]] = []

        for reg in strategies:
            sid = reg.strategy_id
            trades = list(
                self.session.exec(select(TradeRecord).where(TradeRecord.strategy == sid)).all()
            )
            if cutoff:
                trades = [t for t in trades if record_created_after(t, cutoff)]
            closed = [t for t in trades if t.status == "closed" and t.return_pct is not None]
            wins = [t for t in closed if (t.return_pct or 0) > 0]
            losses = [t for t in closed if (t.return_pct or 0) <= 0]

            exec_logs = list(
                self.session.exec(
                    select(ExecutionLog).join(
                        StrategySignal,
                        ExecutionLog.signal_id == StrategySignal.id,
                        isouter=True,
                    ).where(StrategySignal.strategy == sid)
                ).all()
            )
            if cutoff:
                exec_logs = [e for e in exec_logs if record_created_after(e, cutoff)]
            rejects = [e for e in exec_logs if e.status == "paper_order_rejected"]
            blocks = [e for e in exec_logs if e.status == "preflight_blocked"]
            filled = [e for e in exec_logs if e.status == "paper_order_filled"]

            blocker_counts: dict[str, int] = {}
            for b in blocks:
                code = b.reject_reason or "unknown"
                blocker_counts[code] = blocker_counts.get(code, 0) + 1
            top_blocker = max(blocker_counts, key=blocker_counts.get) if blocker_counts else None

            days_running = 0
            if reg.created_at:
                days_running = max(0, (datetime.utcnow() - reg.created_at).days)

            if not closed:
                plain = "Strategy not proven yet — no completed paper trades."
            elif len(wins) < len(losses):
                plain = "Strategy currently losing in paper."
            else:
                plain = f"Paper evidence: {len(closed)} closed trades, {len(wins)} wins."

            exp = sum(t.return_pct or 0 for t in closed) / len(closed) if closed else None
            rows.append(
                {
                    "strategy_id": sid,
                    "status": reg.current_stage,
                    "current_stage": reg.current_stage,
                    "days_running": days_running,
                    "trades_count": len(trades),
                    "fills": len(filled),
                    "closed_trades": len(closed),
                    "wins": len(wins),
                    "losses": len(losses),
                    "expectancy_pct": round(exp, 4) if exp is not None else None,
                    "rejection_rate": round(len(rejects) / max(len(exec_logs), 1), 4),
                    "most_common_blocker": top_blocker,
                    "plain_summary": plain,
                    "confidence": reg.confidence if hasattr(reg, "confidence") else None,
                    "promotion_stage": reg.current_stage,
                }
            )

        return {
            "status": "ok",
            "reset_epoch": epoch,
            "strategies": rows,
            "honest_disclaimer": "Performance reflects paper epoch only — not live results.",
        }
